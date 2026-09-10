"""Pure balance rules and application-service error translation."""

import asyncio
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest

from erp.modules.inventory.application import InventoryBalanceService, InventoryBalanceStore
from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.domain import (
    InventoryBalance,
    InventoryPosting,
    InventoryState,
    InventoryTransaction,
    InventoryTransactionType,
)
from erp.platform.errors import ApplicationError


def _entry(quantity: str = "5") -> InventoryLedgerEntry:
    company_id = uuid4()
    transaction = InventoryTransaction.create(
        company_id=company_id,
        transaction_type=InventoryTransactionType.ADJUSTMENT,
        reference_type="BALANCE_TEST",
        created_by=uuid4(),
    )
    posting = InventoryPosting.create(
        company_id=company_id,
        transaction_id=transaction.id,
        sequence=1,
        product_id=uuid4(),
        warehouse_id=uuid4(),
        quantity_delta=Decimal(quantity),
        state=InventoryState.AVAILABLE,
    )
    return InventoryLedgerEntry(transaction, (posting,))


class FailingStore:
    async def apply_ledger_entry(self, entry: InventoryLedgerEntry) -> tuple[InventoryBalance, ...]:
        raise ValueError("inventory balance cannot become negative.")


def test_balance_starts_from_positive_posting_and_versions_changes() -> None:
    posting = _entry("5").postings[0]
    balance = InventoryBalance.from_posting(posting)

    assert balance.quantity.value == Decimal("5")
    assert balance.version == 1
    changed = balance.apply(Decimal("2.5"))
    assert changed.quantity.value == Decimal("7.5")
    assert changed.version == 2
    with pytest.raises(ValueError, match="negative"):
        changed.apply(Decimal("-8"))
    with pytest.raises(ValueError, match="negative"):
        InventoryBalance.from_posting(_entry("-1").postings[0])


def test_balance_service_translates_negative_balance_to_error_contract() -> None:
    async def scenario() -> None:
        service = InventoryBalanceService(cast(InventoryBalanceStore, FailingStore()))
        with pytest.raises(ApplicationError) as captured:
            await service.apply_ledger_entry(_entry())
        assert captured.value.code == "INVENTORY_NEGATIVE_BALANCE"
        assert captured.value.status_code == 409

    asyncio.run(scenario())
