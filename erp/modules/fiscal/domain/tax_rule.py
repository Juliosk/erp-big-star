"""Pure M11 tax-rule value objects and aggregate."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from erp.modules.fiscal.domain.exceptions import (
    InvalidTaxRuleError,
    InvalidTaxRuleTransitionError,
    TaxRuleSodViolationError,
)

_RATE_QUANTUM = Decimal("0.0001")


def _uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidTaxRuleError(f"{field} must be a non-zero UUID.")
    return value


def _identifier(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidTaxRuleError(f"{field} must be text.")
    normalized = value.strip().upper()
    if not normalized or len(normalized) > maximum or re.fullmatch(r"[A-Z0-9._/-]+", normalized) is None:
        raise InvalidTaxRuleError(f"{field} must be a canonical identifier.")
    return normalized


def _digits(value: str, field: str, length: int) -> str:
    if not isinstance(value, str) or re.fullmatch(rf"\d{{{length}}}", value.strip()) is None:
        raise InvalidTaxRuleError(f"{field} must contain {length} digits.")
    return value.strip()


def _rate(value: Decimal, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidTaxRuleError(f"{field} must be a finite Decimal.")
    try:
        normalized = value.quantize(_RATE_QUANTUM)
    except InvalidOperation as error:
        raise InvalidTaxRuleError(f"{field} uses unsupported precision.") from error
    if normalized != value or not Decimal("0") <= normalized <= Decimal("1"):
        raise InvalidTaxRuleError(f"{field} must be between 0 and 1 with four decimals.")
    return normalized


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidTaxRuleError(f"{field} must be timezone-aware.")
    return value


class FiscalFlow(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class TaxRuleStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class TaxJurisdiction:
    country_code: str
    state_code: str | None = None
    municipality_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.country_code, str) or re.fullmatch(
            r"[A-Z]{2}", self.country_code.strip().upper()
        ) is None:
            raise InvalidTaxRuleError("country_code must use ISO alpha-2 format.")
        object.__setattr__(self, "country_code", self.country_code.strip().upper())
        if self.state_code is not None:
            if not isinstance(self.state_code, str) or re.fullmatch(
                r"[A-Z]{2}", self.state_code.strip().upper()
            ) is None:
                raise InvalidTaxRuleError("state_code must contain two letters.")
            object.__setattr__(self, "state_code", self.state_code.strip().upper())
        if self.municipality_code is not None:
            if self.state_code is None:
                raise InvalidTaxRuleError("municipality_code requires state_code.")
            object.__setattr__(
                self,
                "municipality_code",
                _digits(self.municipality_code, "municipality_code", 7),
            )


@dataclass(frozen=True, slots=True)
class TaxRuleCriteria:
    flow: FiscalFlow
    ncm: str
    cfop: str
    origin: TaxJurisdiction
    destination: TaxJurisdiction

    def __post_init__(self) -> None:
        if not isinstance(self.flow, FiscalFlow):
            raise InvalidTaxRuleError("flow must be a FiscalFlow.")
        object.__setattr__(self, "ncm", _digits(self.ncm, "ncm", 8))
        object.__setattr__(self, "cfop", _digits(self.cfop, "cfop", 4))
        if not isinstance(self.origin, TaxJurisdiction) or not isinstance(
            self.destination, TaxJurisdiction
        ):
            raise InvalidTaxRuleError("origin and destination must be TaxJurisdiction values.")


@dataclass(frozen=True, slots=True)
class TaxRateProfile:
    icms: Decimal
    pis: Decimal
    cofins: Decimal
    ipi: Decimal

    def __post_init__(self) -> None:
        for field in ("icms", "pis", "cofins", "ipi"):
            object.__setattr__(self, field, _rate(getattr(self, field), field))


@dataclass(frozen=True, slots=True)
class TaxRule:
    id: UUID
    company_id: UUID
    code: str
    version_code: str
    criteria: TaxRuleCriteria
    rates: TaxRateProfile
    effective_from: date
    effective_until: date | None
    created_by: UUID
    status: TaxRuleStatus = TaxRuleStatus.DRAFT
    version: int = 1
    activated_by: UUID | None = None
    activated_at: datetime | None = None
    retired_at: datetime | None = None

    def __post_init__(self) -> None:
        for field in ("id", "company_id", "created_by"):
            _uuid(getattr(self, field), field)
        object.__setattr__(self, "code", _identifier(self.code, "code", 40))
        object.__setattr__(
            self, "version_code", _identifier(self.version_code, "version_code", 32)
        )
        if not isinstance(self.criteria, TaxRuleCriteria) or not isinstance(
            self.rates, TaxRateProfile
        ):
            raise InvalidTaxRuleError("criteria and rates must use fiscal value objects.")
        if not isinstance(self.effective_from, date):
            raise InvalidTaxRuleError("effective_from must be a date.")
        if self.effective_until is not None and self.effective_until < self.effective_from:
            raise InvalidTaxRuleError("effective_until cannot predate effective_from.")
        if not isinstance(self.status, TaxRuleStatus):
            raise InvalidTaxRuleError("status must be a TaxRuleStatus.")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise InvalidTaxRuleError("version must be a positive integer.")
        self._validate_evidence()

    def activate(self, *, actor_id: UUID, occurred_at: datetime) -> TaxRule:
        if self.status is not TaxRuleStatus.DRAFT:
            raise InvalidTaxRuleTransitionError("Only a draft tax rule can be activated.")
        actor = _uuid(actor_id, "actor_id")
        if actor == self.created_by:
            raise TaxRuleSodViolationError("Tax-rule editor cannot activate the same version.")
        return replace(
            self,
            status=TaxRuleStatus.ACTIVE,
            version=self.version + 1,
            activated_by=actor,
            activated_at=_aware(occurred_at, "occurred_at"),
        )

    def retire(self, *, occurred_at: datetime) -> TaxRule:
        if self.status is not TaxRuleStatus.ACTIVE:
            raise InvalidTaxRuleTransitionError("Only an active tax rule can be retired.")
        instant = _aware(occurred_at, "occurred_at")
        assert self.activated_at is not None
        if instant < self.activated_at:
            raise InvalidTaxRuleError("retired_at cannot predate activation.")
        return replace(
            self,
            status=TaxRuleStatus.RETIRED,
            version=self.version + 1,
            retired_at=instant,
        )

    def applies_on(self, value: date) -> bool:
        if not isinstance(value, date):
            raise InvalidTaxRuleError("value must be a date.")
        return (
            self.status is TaxRuleStatus.ACTIVE
            and value >= self.effective_from
            and (self.effective_until is None or value <= self.effective_until)
        )

    def _validate_evidence(self) -> None:
        if self.activated_by is not None:
            _uuid(self.activated_by, "activated_by")
        if self.activated_at is not None:
            _aware(self.activated_at, "activated_at")
        if self.retired_at is not None:
            _aware(self.retired_at, "retired_at")
        if self.status is TaxRuleStatus.DRAFT and any(
            value is not None for value in (self.activated_by, self.activated_at, self.retired_at)
        ):
            raise InvalidTaxRuleError("Draft tax rules cannot carry lifecycle evidence.")
        if self.status in {TaxRuleStatus.ACTIVE, TaxRuleStatus.RETIRED} and (
            self.activated_by is None or self.activated_at is None
        ):
            raise InvalidTaxRuleError("Activated tax-rule states require activation evidence.")
        if (self.status is TaxRuleStatus.RETIRED) != (self.retired_at is not None):
            raise InvalidTaxRuleError("retired_at is exclusive to retired tax rules.")
        if (
            self.retired_at is not None
            and self.activated_at is not None
            and self.retired_at < self.activated_at
        ):
            raise InvalidTaxRuleError("retired_at cannot predate activation.")


__all__ = [
    "FiscalFlow",
    "TaxJurisdiction",
    "TaxRateProfile",
    "TaxRule",
    "TaxRuleCriteria",
    "TaxRuleStatus",
]
