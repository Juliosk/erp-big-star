"""Database-owned transactional application adapter for inventory balances."""

from erp.modules.inventory.application.balances import InventoryBalanceStore
from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.domain import InventoryBalance
from erp.modules.inventory.infrastructure.balance_repository import InventoryBalanceRepository
from erp.modules.inventory.infrastructure.ledger_repository import InventoryLedgerRepository
from erp.platform.database import Database


class PostgresInventoryBalances(InventoryBalanceStore):
    """Append ledger facts and update balances atomically in one PostgreSQL transaction."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def apply_ledger_entry(self, entry: InventoryLedgerEntry) -> tuple[InventoryBalance, ...]:
        async with self._database.session() as session, session.begin():
            await InventoryLedgerRepository(session, company_id=entry.company_id).append(entry)
            repository = InventoryBalanceRepository(session, company_id=entry.company_id)
            return tuple([await repository.apply(posting) for posting in entry.postings])


__all__ = ["PostgresInventoryBalances"]
