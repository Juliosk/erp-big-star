"""Shared inventory value objects."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class InventoryState(StrEnum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    QUARANTINE = "QUARANTINE"
    DAMAGED = "DAMAGED"
    BLOCKED = "BLOCKED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVING_STAGE = "RECEIVING_STAGE"


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise ValueError("quantity must be represented as Decimal.")
        if not self.value.is_finite():
            raise ValueError("quantity must be finite.")
        if self.value < Decimal("0"):
            raise ValueError("quantity cannot be negative.")
        exponent = self.value.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -6:
            raise ValueError("quantity supports at most six decimal places.")

    @classmethod
    def of(cls, value: str | int | Decimal) -> Quantity:
        return cls(Decimal(value))


__all__ = ["InventoryState", "Quantity"]
