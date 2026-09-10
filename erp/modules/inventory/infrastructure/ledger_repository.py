"""Append-only PostgreSQL repository for M5 inventory ledger facts."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.domain import (
    InventoryPosting,
    InventoryTransaction,
    InventoryTransactionType,
)
from erp.modules.inventory.domain.stock import InventoryState
from erp.modules.inventory.infrastructure.ledger_model import (
    InventoryPostingModel,
    InventoryTransactionModel,
)
from erp.platform.errors import ApplicationError


class InventoryLedgerRepository:
    """Persist immutable transaction headers and posting lines inside one tenant."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def append(self, entry: InventoryLedgerEntry) -> InventoryLedgerEntry:
        if entry.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The inventory ledger entry is outside the selected company.",
                status_code=403,
            )
        self._session.add(
            InventoryTransactionModel(
                id=entry.transaction.id,
                company_id=self._company_id,
                transaction_type=entry.transaction.transaction_type,
                reference_type=entry.transaction.reference_type,
                reference_id=entry.transaction.reference_id,
                occurred_at=entry.transaction.occurred_at,
                created_by=entry.transaction.created_by,
            )
        )
        await self._session.flush()
        for posting in entry.postings:
            self._session.add(
                InventoryPostingModel(
                    id=posting.id,
                    company_id=self._company_id,
                    transaction_id=posting.transaction_id,
                    sequence=posting.sequence,
                    product_id=posting.product_id,
                    warehouse_id=posting.warehouse_id,
                    location_id=posting.location_id,
                    lot_id=posting.lot_id,
                    pool_id=posting.pool_id,
                    state=posting.state,
                    quantity_delta=posting.quantity_delta,
                )
            )
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code="INVENTORY_LEDGER_CONFLICT",
                    message="This inventory ledger entry already exists.",
                    status_code=409,
                ) from error
            raise
        return entry

    async def get_postings(self, transaction_id: UUID) -> tuple[InventoryPosting, ...]:
        result = await self._session.scalars(
            select(InventoryPostingModel)
            .where(
                InventoryPostingModel.company_id == self._company_id,
                InventoryPostingModel.transaction_id == transaction_id,
            )
            .order_by(InventoryPostingModel.sequence)
        )
        return tuple(_posting(model) for model in result)


def _transaction(model: InventoryTransactionModel) -> InventoryTransaction:
    return InventoryTransaction(
        id=model.id,
        company_id=model.company_id,
        transaction_type=InventoryTransactionType(model.transaction_type),
        reference_type=model.reference_type,
        reference_id=model.reference_id,
        occurred_at=model.occurred_at,
        created_by=model.created_by,
    )


def _posting(model: InventoryPostingModel) -> InventoryPosting:
    return InventoryPosting(
        id=model.id,
        company_id=model.company_id,
        transaction_id=model.transaction_id,
        sequence=model.sequence,
        product_id=model.product_id,
        warehouse_id=model.warehouse_id,
        location_id=model.location_id,
        lot_id=model.lot_id,
        pool_id=model.pool_id,
        state=InventoryState(model.state),
        quantity_delta=model.quantity_delta,
    )


__all__ = ["InventoryLedgerRepository", "_posting", "_transaction"]
