"""Tenant-bound persistence adapter for M12 provisional financial entries."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.domain import (
    FinanceScopeError,
    FinanceVersionConflictError,
    PayableConflictError,
    ProvisionalEntryOrigin,
    ProvisionalEntryStatus,
    ProvisionalFinancialEntry,
)
from erp.modules.finance.infrastructure.payable_model import ProvisionalEntryModel


class ProvisionalEntryRepository:
    """Persist source-linked provisions without managing transactions."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, entry: ProvisionalFinancialEntry, *, actor_id: UUID) -> None:
        self._write_scope(entry, actor_id)
        if entry.version != 1 or entry.status is not ProvisionalEntryStatus.OPEN:
            raise ValueError("A new provisional entry must start open at version one.")
        self._session.add(_entry_model(entry, actor_id))
        await self._flush()

    async def get(self, entry_id: UUID) -> ProvisionalFinancialEntry | None:
        model = await self._session.scalar(
            select(ProvisionalEntryModel)
            .where(
                ProvisionalEntryModel.company_id == self._company_id,
                ProvisionalEntryModel.id == entry_id,
            )
            .execution_options(populate_existing=True)
        )
        return None if model is None else _entry(model)

    async def get_by_source(
        self,
        *,
        origin: ProvisionalEntryOrigin,
        source_id: UUID,
        source_version: int,
    ) -> ProvisionalFinancialEntry | None:
        model = await self._session.scalar(
            select(ProvisionalEntryModel)
            .where(
                ProvisionalEntryModel.company_id == self._company_id,
                ProvisionalEntryModel.origin == origin.value,
                ProvisionalEntryModel.source_id == source_id,
                ProvisionalEntryModel.source_version == source_version,
            )
            .execution_options(populate_existing=True)
        )
        return None if model is None else _entry(model)

    async def get_by_source_id(
        self,
        *,
        origin: ProvisionalEntryOrigin,
        source_id: UUID,
    ) -> ProvisionalFinancialEntry | None:
        models = tuple(
            await self._session.scalars(
                select(ProvisionalEntryModel)
                .where(
                    ProvisionalEntryModel.company_id == self._company_id,
                    ProvisionalEntryModel.origin == origin.value,
                    ProvisionalEntryModel.source_id == source_id,
                )
                .order_by(ProvisionalEntryModel.source_version.desc())
                .limit(2)
                .execution_options(populate_existing=True)
            )
        )
        if len(models) > 1:
            raise PayableConflictError("Multiple provisions exist for the same source aggregate.")
        return None if not models else _entry(models[0])

    async def find_purchase_order_match(
        self,
        *,
        supplier_tax_id: str,
        amount: Decimal,
    ) -> ProvisionalFinancialEntry | None:
        models = tuple(
            await self._session.scalars(
                select(ProvisionalEntryModel)
                .where(
                    ProvisionalEntryModel.company_id == self._company_id,
                    ProvisionalEntryModel.origin
                    == ProvisionalEntryOrigin.APPROVED_PURCHASE_ORDER.value,
                    ProvisionalEntryModel.supplier_tax_id == supplier_tax_id,
                    ProvisionalEntryModel.amount == amount,
                )
                .order_by(ProvisionalEntryModel.created_at.desc())
                .limit(2)
                .execution_options(populate_existing=True)
            )
        )
        if len(models) > 1:
            raise PayableConflictError(
                "Multiple purchase-order provisions match this supplier and amount."
            )
        return None if not models else _entry(models[0])

    async def save(
        self,
        entry: ProvisionalFinancialEntry,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> ProvisionalFinancialEntry:
        self._write_scope(entry, actor_id)
        compare = entry.version - 1 if expected_version is None else expected_version
        if compare < 1 or entry.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        updated = cast(
            CursorResult[Any],
            await self._session.execute(
                update(ProvisionalEntryModel)
                .where(
                    ProvisionalEntryModel.company_id == self._company_id,
                    ProvisionalEntryModel.id == entry.id,
                    ProvisionalEntryModel.version == compare,
                    ProvisionalEntryModel.origin == entry.origin.value,
                    ProvisionalEntryModel.source_id == entry.source_id,
                    ProvisionalEntryModel.source_version == entry.source_version,
                )
                .values(**_entry_values(entry, actor_id)),
            ),
        )
        if updated.rowcount != 1:
            raise FinanceVersionConflictError(
                f"Provisional entry expected version {compare} is stale."
            )
        await self._session.flush()
        return entry

    def _write_scope(self, entry: ProvisionalFinancialEntry, actor_id: UUID) -> None:
        if entry.company_id != self._company_id:
            raise FinanceScopeError("Provisional entry is outside the selected company.")
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            self._translate(error)

    @staticmethod
    def _translate(error: IntegrityError) -> None:
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise PayableConflictError(
                "A provisional entry already exists for this source and company."
            ) from error
        raise error


def _entry_model(entry: ProvisionalFinancialEntry, actor_id: UUID) -> ProvisionalEntryModel:
    return ProvisionalEntryModel(
        id=entry.id,
        company_id=entry.company_id,
        created_by=entry.created_by,
        **_entry_values(entry, actor_id),
    )


def _entry_values(entry: ProvisionalFinancialEntry, actor_id: UUID) -> dict[str, Any]:
    return {
        "origin": entry.origin.value,
        "source_id": entry.source_id,
        "source_version": entry.source_version,
        "supplier_id": entry.supplier_id,
        "supplier_tax_id": entry.supplier_tax_id,
        "amount": entry.amount,
        "currency": entry.currency,
        "status": entry.status.value,
        "payable_id": entry.payable_id,
        "void_reason": entry.void_reason,
        "version": entry.version,
        "updated_at": datetime.now(UTC),
        "updated_by": actor_id,
    }


def _entry(model: ProvisionalEntryModel) -> ProvisionalFinancialEntry:
    return ProvisionalFinancialEntry(
        id=model.id,
        company_id=model.company_id,
        origin=ProvisionalEntryOrigin(model.origin),
        source_id=model.source_id,
        source_version=model.source_version,
        supplier_id=model.supplier_id,
        supplier_tax_id=model.supplier_tax_id,
        amount=model.amount,
        currency=model.currency,
        created_by=model.created_by,
        status=ProvisionalEntryStatus(model.status),
        payable_id=model.payable_id,
        void_reason=model.void_reason,
        version=model.version,
    )


__all__ = ["ProvisionalEntryRepository"]
