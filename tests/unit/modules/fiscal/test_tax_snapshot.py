"""Immutable tax snapshot invariants."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from erp.modules.fiscal.domain import (
    InvalidTaxSnapshotError,
    TaxComponentSnapshot,
    TaxKind,
    TaxSnapshot,
)


def component(kind: TaxKind, amount: str) -> TaxComponentSnapshot:
    return TaxComponentSnapshot.create(
        kind=kind,
        tax_code="00",
        taxable_base="100.00",
        rate="1.6500",
        amount=amount,
    )


def test_snapshot_is_normalized_immutable_and_totals_all_supported_taxes() -> None:
    snapshot = TaxSnapshot(
        icms=component(TaxKind.ICMS, "18"),
        pis=component(TaxKind.PIS, "1.65"),
        cofins=component(TaxKind.COFINS, "7.60"),
        ipi=component(TaxKind.IPI, "5"),
    )

    assert snapshot.icms.amount == Decimal("18.00")
    assert snapshot.icms.rate == Decimal("1.6500")
    assert snapshot.total_tax == Decimal("32.25")
    with pytest.raises(FrozenInstanceError):
        snapshot.icms.amount = Decimal("0")  # type: ignore[misc]


@pytest.mark.parametrize("field", ["-1", "NaN", "Infinity", "invalid"])
def test_invalid_tax_values_are_rejected(field: str) -> None:
    with pytest.raises(InvalidTaxSnapshotError):
        TaxComponentSnapshot.create(
            kind=TaxKind.ICMS,
            tax_code="00",
            taxable_base=field,
            rate="1",
            amount="1",
        )


def test_snapshot_rejects_component_in_wrong_tax_slot() -> None:
    icms = component(TaxKind.ICMS, "1")
    with pytest.raises(InvalidTaxSnapshotError):
        TaxSnapshot(icms=icms, pis=icms, cofins=icms, ipi=icms)


def test_tax_code_is_required() -> None:
    with pytest.raises(InvalidTaxSnapshotError):
        TaxComponentSnapshot.create(
            kind=TaxKind.IPI,
            tax_code=" ",
            taxable_base="0",
            rate="0",
            amount="0",
        )
