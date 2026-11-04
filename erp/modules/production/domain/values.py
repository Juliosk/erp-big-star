"""Exact and immutable production value objects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from erp.modules.production.domain.exceptions import InvalidProductionValueError

_QUANTITY_QUANTUM = Decimal("0.000001")
_RATE_QUANTUM = Decimal("0.000001")


def require_uuid(value: object, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidProductionValueError(f"{field} must be a non-zero UUID.")
    return value


def normalized_decimal(
    value: Decimal,
    field: str,
    *,
    quantum: Decimal = _QUANTITY_QUANTUM,
) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidProductionValueError(f"{field} must be a finite Decimal.")
    try:
        return value.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise InvalidProductionValueError(f"{field} has unsupported precision.") from error


class UnitOfMeasure(StrEnum):
    EACH = "EA"
    KILOGRAM = "KG"
    GRAM = "G"
    LITER = "L"
    MILLILITER = "ML"
    METER = "M"
    SQUARE_METER = "M2"


@dataclass(frozen=True, slots=True)
class ProductionQuantity:
    amount: Decimal
    unit: UnitOfMeasure

    def __post_init__(self) -> None:
        amount = normalized_decimal(self.amount, "amount")
        if amount <= 0:
            raise InvalidProductionValueError("amount must be positive.")
        if not isinstance(self.unit, UnitOfMeasure):
            raise InvalidProductionValueError("unit must be a UnitOfMeasure.")
        object.__setattr__(self, "amount", amount)

    def scaled_by(self, factor: Decimal) -> ProductionQuantity:
        normalized_factor = normalized_decimal(factor, "factor")
        if normalized_factor <= 0:
            raise InvalidProductionValueError("factor must be positive.")
        return ProductionQuantity(self.amount * normalized_factor, self.unit)


@dataclass(frozen=True, slots=True)
class ScrapRate:
    """Expected process loss represented as a ratio in the interval [0, 1)."""

    value: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        value = normalized_decimal(self.value, "scrap_rate", quantum=_RATE_QUANTUM)
        if not Decimal("0") <= value < Decimal("1"):
            raise InvalidProductionValueError("scrap_rate must be between 0 (inclusive) and 1.")
        object.__setattr__(self, "value", value)

    def gross_requirement(self, net: ProductionQuantity) -> ProductionQuantity:
        if not isinstance(net, ProductionQuantity):
            raise InvalidProductionValueError("net must be a ProductionQuantity.")
        return ProductionQuantity(net.amount / (Decimal("1") - self.value), net.unit)


@dataclass(frozen=True, slots=True)
class EngineeringVersion:
    code: str
    revision: int
    effective_from: date
    effective_until: date | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str):
            raise InvalidProductionValueError("engineering version code must be text.")
        code = self.code.strip().upper()
        if re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,31}", code) is None:
            raise InvalidProductionValueError("engineering version code is invalid.")
        if type(self.revision) is not int or self.revision < 1:
            raise InvalidProductionValueError("revision must be a positive integer.")
        if type(self.effective_from) is not date:
            raise InvalidProductionValueError("effective_from must be a date.")
        if self.effective_until is not None:
            if type(self.effective_until) is not date:
                raise InvalidProductionValueError("effective_until must be a date.")
            if self.effective_until < self.effective_from:
                raise InvalidProductionValueError("effective_until cannot precede effective_from.")
        object.__setattr__(self, "code", code)


@dataclass(frozen=True, slots=True)
class WorkCenterCode:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise InvalidProductionValueError("work center code must be text.")
        value = self.value.strip().upper()
        if re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,31}", value) is None:
            raise InvalidProductionValueError("work center code is invalid.")
        object.__setattr__(self, "value", value)


__all__ = [
    "EngineeringVersion",
    "ProductionQuantity",
    "ScrapRate",
    "UnitOfMeasure",
    "WorkCenterCode",
]

