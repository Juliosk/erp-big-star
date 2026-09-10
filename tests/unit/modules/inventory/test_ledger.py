"""Pure M5 ledger rules."""

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.domain import (
    InventoryPosting,
    InventoryState,
    InventoryTransaction,
    InventoryTransactionType,
)


def _transaction() -> InventoryTransaction:
    return InventoryTransaction.create(
        company_id=uuid4(),
        transaction_type=InventoryTransactionType.ADJUSTMENT,
        reference_type="MANUAL_ADJUSTMENT",
        created_by=uuid4(),
    )


def _posting(
    transaction: InventoryTransaction, *, sequence: int = 1, quantity: str = "1"
) -> InventoryPosting:
    return InventoryPosting.create(
        company_id=transaction.company_id,
        transaction_id=transaction.id,
        sequence=sequence,
        product_id=uuid4(),
        warehouse_id=uuid4(),
        quantity_delta=Decimal(quantity),
        state=InventoryState.AVAILABLE,
    )


def test_ledger_entry_requires_contiguous_same_transaction_postings() -> None:
    transaction = _transaction()
    first = _posting(transaction, sequence=1)
    second = _posting(transaction, sequence=2, quantity="-1")

    entry = InventoryLedgerEntry(transaction, (first, second))

    assert entry.company_id == transaction.company_id
    assert entry.postings == (first, second)
    with pytest.raises(ValueError, match="at least one"):
        InventoryLedgerEntry(transaction, ())
    with pytest.raises(ValueError, match="contiguous"):
        InventoryLedgerEntry(transaction, (replace(first, sequence=2),))
    with pytest.raises(ValueError, match="company"):
        InventoryLedgerEntry(transaction, (replace(first, company_id=uuid4()),))
    with pytest.raises(ValueError, match="transaction"):
        InventoryLedgerEntry(transaction, (replace(first, transaction_id=uuid4()),))


@pytest.mark.parametrize("value", ["0", "1.1234567", "Infinity"])
def test_posting_rejects_zero_over_precise_or_infinite_deltas(value: str) -> None:
    transaction = _transaction()
    with pytest.raises(ValueError, match="quantity delta"):
        _posting(transaction, quantity=value)


def test_transaction_requires_canonical_reference_type_and_timezone() -> None:
    with pytest.raises(ValueError, match="reference_type"):
        InventoryTransaction.create(
            company_id=uuid4(),
            transaction_type=InventoryTransactionType.ADJUSTMENT,
            reference_type="bad type",
            created_by=uuid4(),
        )
