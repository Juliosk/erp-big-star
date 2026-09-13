"""Money and percentage value objects for pricing decisions."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class Currency(StrEnum):
    BRL = "BRL"


_MONEY_QUANT = Decimal("0.01")
_PERCENTAGE_QUANT = Decimal("0.0001")


def _decimal(value: Decimal | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(value)


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: Currency = Currency.BRL

    def __post_init__(self) -> None:
        if not isinstance(self.currency, Currency):
            raise ValueError("currency must be an official pricing currency.")
        quantized = self.amount.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)
        if quantized < Decimal("0.00"):
            raise ValueError("money amount cannot be negative.")
        object.__setattr__(self, "amount", quantized)

    @classmethod
    def brl(cls, amount: Decimal | str) -> Money:
        return cls(amount=_decimal(amount), currency=Currency.BRL)


@dataclass(frozen=True, slots=True)
class Percentage:
    value: Decimal

    def __post_init__(self) -> None:
        quantized = self.value.quantize(_PERCENTAGE_QUANT, rounding=ROUND_HALF_UP)
        if quantized < Decimal("0.0000") or quantized > Decimal("1.0000"):
            raise ValueError("percentage must be between 0 and 1.")
        object.__setattr__(self, "value", quantized)

    @classmethod
    def ratio(cls, value: Decimal | str) -> Percentage:
        return cls(value=_decimal(value))


__all__ = ["Currency", "Money", "Percentage"]
