"""Technology-neutral balance service for ledger-derived stock quantities."""

from typing import Protocol

from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.domain import InventoryBalance
from erp.platform.errors import ApplicationError, ErrorDetail


class InventoryBalanceStore(Protocol):
    async def apply_ledger_entry(
        self, entry: InventoryLedgerEntry
    ) -> tuple[InventoryBalance, ...]: ...


class InventoryBalanceService:
    """Apply immutable ledger facts to durable balances through a transactional port."""

    def __init__(self, store: InventoryBalanceStore) -> None:
        self._store = store

    async def apply_ledger_entry(self, entry: InventoryLedgerEntry) -> tuple[InventoryBalance, ...]:
        try:
            return await self._store.apply_ledger_entry(entry)
        except ValueError as error:
            raise ApplicationError(
                code="INVENTORY_NEGATIVE_BALANCE",
                message="Inventory balance cannot become negative.",
                status_code=409,
                details=[ErrorDetail(message=str(error))],
            ) from error


__all__ = ["InventoryBalanceService", "InventoryBalanceStore"]
