"""Real PostgreSQL coverage for immutable inventory ledger persistence."""

import asyncio
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import delete, text

from erp.modules.admin.domain import Branch
from erp.modules.admin.infrastructure import BranchModel, BranchRepository
from erp.modules.inventory.application import InventoryLedgerEntry
from erp.modules.inventory.domain import (
    InventoryPosting,
    InventoryState,
    InventoryTransaction,
    InventoryTransactionType,
    Warehouse,
)
from erp.modules.inventory.infrastructure import (
    InventoryLedgerRepository,
    InventoryPostingModel,
    InventoryTransactionModel,
    WarehouseModel,
    WarehouseRepository,
)
from erp.modules.product.infrastructure import ProductRepository
from erp.platform.errors import ApplicationError
from tests.integration.test_product_persistence import Fixture, _cnpj, fixture

pytestmark = pytest.mark.integration


async def _seed_dimensions() -> tuple[AbstractAsyncContextManager[Fixture], Fixture, UUID, UUID]:
    manager = fixture()
    data = await manager.__aenter__()
    branch = Branch.create(
        company_id=data.company_id,
        code="LEDGER",
        name="Ledger branch",
        tax_id=_cnpj(),
        timezone="America/Sao_Paulo",
    )
    product = data.product(code="LEDGER")
    warehouse = Warehouse.create(
        company_id=data.company_id,
        branch_id=branch.id,
        code="WHLEDGER",
        name="Ledger warehouse",
    )
    async with data.database.session() as session, session.begin():
        await BranchRepository().add(session, branch, actor_id=data.actor_id)
        await ProductRepository(session, company_id=data.company_id).add(
            product, actor_id=data.actor_id
        )
        await WarehouseRepository(session, company_id=data.company_id).add(
            warehouse, actor_id=data.actor_id
        )
    return manager, data, product.id, warehouse.id


def _entry(
    *, company_id: UUID, actor_id: UUID, product_id: UUID, warehouse_id: UUID
) -> InventoryLedgerEntry:
    transaction = InventoryTransaction.create(
        company_id=company_id,
        transaction_type=InventoryTransactionType.ADJUSTMENT,
        reference_type="TEST_ADJUSTMENT",
        created_by=actor_id,
    )
    posting = InventoryPosting.create(
        company_id=company_id,
        transaction_id=transaction.id,
        sequence=1,
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity_delta=Decimal("5"),
        state=InventoryState.AVAILABLE,
    )
    return InventoryLedgerEntry(transaction, (posting,))


def test_ledger_append_round_trip_and_database_append_only_guards() -> None:
    async def scenario() -> None:
        manager, data, product_id, warehouse_id = await _seed_dimensions()
        try:
            entry = _entry(
                company_id=data.company_id,
                actor_id=data.actor_id,
                product_id=product_id,
                warehouse_id=warehouse_id,
            )
            async with data.database.session() as session, session.begin():
                repository = InventoryLedgerRepository(session, company_id=data.company_id)
                assert await repository.append(entry) == entry
                assert await repository.get_postings(entry.transaction.id) == entry.postings
            async with data.database.session() as session:
                with pytest.raises(Exception, match="append-only"):
                    await session.execute(
                        text(
                            """
                            UPDATE inventory.inventory_posting
                            SET quantity_delta = quantity_delta + 1
                            WHERE id = :posting_id
                            """
                        ),
                        {"posting_id": entry.postings[0].id},
                    )
                await session.rollback()
            async with data.database.session() as session:
                with pytest.raises(Exception, match="append-only"):
                    await session.execute(
                        text("DELETE FROM inventory.inventory_posting WHERE id = :id"),
                        {"id": entry.postings[0].id},
                    )
                await session.rollback()
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(text("SET LOCAL erp.allow_ledger_cleanup = 'on'"))
                await session.execute(
                    delete(InventoryPostingModel).where(
                        InventoryPostingModel.company_id == data.company_id
                    )
                )
                await session.execute(
                    delete(InventoryTransactionModel).where(
                        InventoryTransactionModel.company_id == data.company_id
                    )
                )
                await session.execute(
                    delete(WarehouseModel).where(WarehouseModel.company_id == data.company_id)
                )
                await session.execute(
                    delete(BranchModel).where(BranchModel.company_id == data.company_id)
                )
            await manager.__aexit__(None, None, None)

    asyncio.run(scenario())


def test_ledger_repository_rejects_cross_company_entry_before_writing() -> None:
    async def scenario() -> None:
        manager, data, product_id, warehouse_id = await _seed_dimensions()
        try:
            entry = _entry(
                company_id=data.other_company_id,
                actor_id=data.actor_id,
                product_id=product_id,
                warehouse_id=warehouse_id,
            )
            async with data.database.session() as session, session.begin():
                with pytest.raises(ApplicationError) as captured:
                    await InventoryLedgerRepository(session, company_id=data.company_id).append(
                        entry
                    )
                assert captured.value.code == "SCOPE_FORBIDDEN"
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(WarehouseModel).where(WarehouseModel.company_id == data.company_id)
                )
                await session.execute(
                    delete(BranchModel).where(BranchModel.company_id == data.company_id)
                )
            await manager.__aexit__(None, None, None)

    asyncio.run(scenario())
