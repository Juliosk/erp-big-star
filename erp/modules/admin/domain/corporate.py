"""Corporate hierarchy aggregate roots owned by M1."""

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from erp.modules.admin.domain.tax_id import Cnpj

_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,29}$")


class CorporateStatus(StrEnum):
    """Supported lifecycle states for the initial corporate foundation."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


def normalize_corporate_code(value: str) -> str:
    """Normalize and validate a stable human-facing business key."""
    normalized = value.strip().upper()
    if _CODE_PATTERN.fullmatch(normalized) is None:
        raise ValueError("Corporate code must contain 2-30 uppercase letters, digits, _ or -.")
    return normalized


def normalize_name(value: str, *, field_name: str) -> str:
    """Reject blank or oversized corporate display/legal names."""
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > 200:
        raise ValueError(f"{field_name} must contain between 1 and 200 characters.")
    return normalized


def validate_timezone(value: str) -> str:
    """Require a real IANA timezone identifier for local-time interpretation."""
    normalized = value.strip()
    try:
        ZoneInfo(normalized)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("timezone must be a valid IANA timezone.") from error
    return normalized


@dataclass(frozen=True, slots=True)
class EconomicGroup:
    """Top-level consolidation boundary; never a transactional tenant by itself."""

    id: UUID
    code: str
    name: str
    status: CorporateStatus
    version: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", normalize_corporate_code(self.code))
        object.__setattr__(self, "name", normalize_name(self.name, field_name="name"))
        object.__setattr__(self, "status", CorporateStatus(self.status))
        if self.version < 1:
            raise ValueError("version must be positive.")

    @classmethod
    def create(cls, *, code: str, name: str, group_id: UUID | None = None) -> Self:
        """Create an active group at version one."""
        return cls(
            id=group_id or uuid4(),
            code=normalize_corporate_code(code),
            name=normalize_name(name, field_name="name"),
            status=CorporateStatus.ACTIVE,
            version=1,
        )

    def deactivate(self) -> Self:
        """Return the next inactive version without mutating history in memory."""
        if self.status is CorporateStatus.INACTIVE:
            return self
        return replace(self, status=CorporateStatus.INACTIVE, version=self.version + 1)

    def activate(self) -> Self:
        """Return the next active version."""
        if self.status is CorporateStatus.ACTIVE:
            return self
        return replace(self, status=CorporateStatus.ACTIVE, version=self.version + 1)


@dataclass(frozen=True, slots=True)
class Company:
    """Legal-company aggregate within exactly one economic group."""

    id: UUID
    group_id: UUID
    code: str
    legal_name: str
    trade_name: str | None
    tax_id: Cnpj
    timezone: str
    status: CorporateStatus
    version: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", normalize_corporate_code(self.code))
        object.__setattr__(
            self,
            "legal_name",
            normalize_name(self.legal_name, field_name="legal_name"),
        )
        if self.trade_name is not None:
            object.__setattr__(
                self,
                "trade_name",
                normalize_name(self.trade_name, field_name="trade_name"),
            )
        if not isinstance(self.tax_id, Cnpj):
            raise TypeError("tax_id must be a Cnpj value object.")
        object.__setattr__(self, "timezone", validate_timezone(self.timezone))
        object.__setattr__(self, "status", CorporateStatus(self.status))
        if self.version < 1:
            raise ValueError("version must be positive.")

    @classmethod
    def create(
        cls,
        *,
        group_id: UUID,
        code: str,
        legal_name: str,
        trade_name: str | None,
        tax_id: str,
        timezone: str,
        company_id: UUID | None = None,
    ) -> Self:
        """Create an active legal company with normalized fiscal identity."""
        normalized_trade_name = (
            normalize_name(trade_name, field_name="trade_name") if trade_name else None
        )
        return cls(
            id=company_id or uuid4(),
            group_id=group_id,
            code=normalize_corporate_code(code),
            legal_name=normalize_name(legal_name, field_name="legal_name"),
            trade_name=normalized_trade_name,
            tax_id=Cnpj(tax_id),
            timezone=validate_timezone(timezone),
            status=CorporateStatus.ACTIVE,
            version=1,
        )

    def deactivate(self) -> Self:
        """Return the next inactive version."""
        if self.status is CorporateStatus.INACTIVE:
            return self
        return replace(self, status=CorporateStatus.INACTIVE, version=self.version + 1)

    def activate(self) -> Self:
        """Return the next active version."""
        if self.status is CorporateStatus.ACTIVE:
            return self
        return replace(self, status=CorporateStatus.ACTIVE, version=self.version + 1)


@dataclass(frozen=True, slots=True)
class Branch:
    """Operational/fiscal establishment within exactly one legal company."""

    id: UUID
    company_id: UUID
    code: str
    name: str
    tax_id: Cnpj
    timezone: str
    status: CorporateStatus
    version: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", normalize_corporate_code(self.code))
        object.__setattr__(self, "name", normalize_name(self.name, field_name="name"))
        if not isinstance(self.tax_id, Cnpj):
            raise TypeError("tax_id must be a Cnpj value object.")
        object.__setattr__(self, "timezone", validate_timezone(self.timezone))
        object.__setattr__(self, "status", CorporateStatus(self.status))
        if self.version < 1:
            raise ValueError("version must be positive.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        code: str,
        name: str,
        tax_id: str,
        timezone: str,
        branch_id: UUID | None = None,
    ) -> Self:
        """Create an active branch with its own fiscal identity and timezone."""
        return cls(
            id=branch_id or uuid4(),
            company_id=company_id,
            code=normalize_corporate_code(code),
            name=normalize_name(name, field_name="name"),
            tax_id=Cnpj(tax_id),
            timezone=validate_timezone(timezone),
            status=CorporateStatus.ACTIVE,
            version=1,
        )

    def deactivate(self) -> Self:
        """Return the next inactive version."""
        if self.status is CorporateStatus.INACTIVE:
            return self
        return replace(self, status=CorporateStatus.INACTIVE, version=self.version + 1)

    def activate(self) -> Self:
        """Return the next active version."""
        if self.status is CorporateStatus.ACTIVE:
            return self
        return replace(self, status=CorporateStatus.ACTIVE, version=self.version + 1)


__all__ = [
    "Branch",
    "Company",
    "CorporateStatus",
    "EconomicGroup",
    "normalize_corporate_code",
    "validate_timezone",
]
