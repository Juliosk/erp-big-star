"""Immutable fiscal tax snapshot value objects."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Self

from erp.modules.fiscal.domain.exceptions import InvalidTaxSnapshotError

MONEY_QUANTUM = Decimal("0.01")
RATE_QUANTUM = Decimal("0.0001")


class TaxKind(StrEnum):
    ICMS = "ICMS"
    PIS = "PIS"
    COFINS = "COFINS"
    IPI = "IPI"


@dataclass(frozen=True, slots=True)
class TaxComponentSnapshot:
    kind: TaxKind
    tax_code: str
    taxable_base: Decimal
    rate: Decimal
    amount: Decimal

    @classmethod
    def create(
        cls,
        *,
        kind: TaxKind,
        tax_code: str,
        taxable_base: Decimal | str,
        rate: Decimal | str,
        amount: Decimal | str,
    ) -> Self:
        code = tax_code.strip().upper()
        if not code or len(code) > 16:
            raise InvalidTaxSnapshotError("Tax code must contain between 1 and 16 characters.")
        base = _decimal(taxable_base, MONEY_QUANTUM, "taxable base")
        normalized_rate = _decimal(rate, RATE_QUANTUM, "tax rate")
        normalized_amount = _decimal(amount, MONEY_QUANTUM, "tax amount")
        if base < 0 or normalized_rate < 0 or normalized_amount < 0:
            raise InvalidTaxSnapshotError("Tax values cannot be negative.")
        return cls(kind, code, base, normalized_rate, normalized_amount)


@dataclass(frozen=True, slots=True)
class TaxSnapshot:
    icms: TaxComponentSnapshot
    pis: TaxComponentSnapshot
    cofins: TaxComponentSnapshot
    ipi: TaxComponentSnapshot

    def __post_init__(self) -> None:
        expected = (
            (self.icms, TaxKind.ICMS),
            (self.pis, TaxKind.PIS),
            (self.cofins, TaxKind.COFINS),
            (self.ipi, TaxKind.IPI),
        )
        if any(component.kind is not kind for component, kind in expected):
            raise InvalidTaxSnapshotError("Each tax snapshot field must match its tax kind.")

    @property
    def total_tax(self) -> Decimal:
        return sum(
            (self.icms.amount, self.pis.amount, self.cofins.amount, self.ipi.amount),
            start=Decimal("0.00"),
        ).quantize(MONEY_QUANTUM)


def _decimal(value: Decimal | str, quantum: Decimal, field: str) -> Decimal:
    try:
        normalized = Decimal(value).quantize(quantum)
    except (InvalidOperation, ValueError) as error:
        raise InvalidTaxSnapshotError(f"Invalid {field}.") from error
    if not normalized.is_finite():
        raise InvalidTaxSnapshotError(f"Invalid {field}.")
    return normalized


__all__ = ["TaxComponentSnapshot", "TaxKind", "TaxSnapshot"]
