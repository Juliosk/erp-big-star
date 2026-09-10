"""Real PostgreSQL tests for transactional and versioned inventory balances."""

import asyncio
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import delete, select, text

from erp.modules.admin.domain import Branch
from erp.modules.admin.infrastructure import BranchModel, BranchRepository
from erp.modules.inventory.application import InventoryBalanceService, InventoryLedgerEntry
from erp.modules.inventory.domain import (
    InventoryPosting,
    InventoryState,
    InventoryTransaction,
    InventoryTransactionType,
    Warehouse,
)
from erp.modules.inventory.infrastructure import (
    InventoryBalanceModel,
    InventoryBalanceRepository,
    InventoryLedgerRepository,
    InventoryPostingModel,
    InventoryTransactionModel,
    PostgresInventoryBalances,
    WarehouseModel,
    WarehouseRepository,
)
from erp.modules.product.infrastructure import ProductRepository
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError
from tests.integration.test_product_persistence import Fixture, _cnpj, fixture

pytestmark = pytest.mark.integration


async def _seed_dimensions() -> tuple[AbstractAsyncContextManager[Fixture], Fixture, UUID, UUID]:
    manager = fixture()
    data = await manager.__aenter__()
    branch = Branch.create(
        company_id=data.company_id,
        code="BALANCE",
        name="Balance branch",
        tax_id=_cnpj(),
        timezone="America/Sao_Paulo",
    )
    product = data.product(code="BALANCE")
    warehouse = Warehouse.create(
        company_id=data.company_id,
        branch_id=branch.id,
        code="WHBALANCE",
        name="Balance warehouse",
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
    *, company_id: UUID, actor_id: UUID, product_id: UUID, warehouse_id: UUID, quantity: str
) -> InventoryLedgerEntry:
    transaction = InventoryTransaction.create(
        company_id=company_id,
        transaction_type=InventoryTransactionType.ADJUSTMENT,
        reference_type="BALANCE_TEST",
        created_by=actor_id,
    )
    posting = InventoryPosting.create(
        company_id=company_id,
        transaction_id=transaction.id,
        sequence=1,
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity_delta=Decimal(quantity),
        state=InventoryState.AVAILABLE,
    )
    return InventoryLedgerEntry(transaction, (posting,))


async def _cleanup(manager: AbstractAsyncContextManager[Fixture], data: Fixture) -> None:
    async with data.database.session() as session, session.begin():
        await session.execute(text("SET LOCAL erp.allow_ledger_cleanup = 'on'"))
        await session.execute(
            delete(InventoryBalanceModel).where(InventoryBalanceModel.company_id == data.company_id)
        )
        await session.execute(
            delete(InventoryPostingModel).where(InventoryPostingModel.company_id == data.company_id)
        )
        await session.execute(
            delete(InventoryTransactionModel).where(
                InventoryTransactionModel.company_id == data.company_id
            )
        )
        await session.execute(
            delete(WarehouseModel).where(WarehouseModel.company_id == data.company_id)
        )
        await session.execute(delete(BranchModel).where(BranchModel.company_id == data.company_id))
    await manager.__aexit__(None, None, None)


def test_balance_service_applies_ledger_and_versions_existing_balance() -> None:
    async def scenario() -> None:
        manager, data, product_id, warehouse_id = await _seed_dimensions()
        try:
            service = InventoryBalanceService(PostgresInventoryBalances(data.database))
            first = await service.apply_ledger_entry(
                _entry(
                    company_id=data.company_id,
                    actor_id=data.actor_id,
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    quantity="5",
                )
            )
            second = await service.apply_ledger_entry(
                _entry(
                    company_id=data.company_id,
                    actor_id=data.actor_id,
                    product_id=product_id,
                    warehouse_id=warehouse_id,
                    quantity="2.5",
                )
            )
            assert first[0].quantity.value == Decimal("5.000000")
            assert first[0].version == 1
            assert second[0].quantity.value == Decimal("7.500000")
            assert second[0].version == 2
            async with data.database.session() as session:
                assert (
                    await session.scalar(
                        select(InventoryPostingModel).where(
                            InventoryPostingModel.company_id == data.company_id
                        )
                    )
                    is not None
                )
        finally:
            await _cleanup(manager, data)

    asyncio.run(scenario())


def test_negative_balance_rolls_back_ledger_and_returns_stable_error() -> None:
    async def scenario() -> None:
        manager, data, product_id, warehouse_id = await _seed_dimensions()
        try:
            service = InventoryBalanceService(PostgresInventoryBalances(data.database))
            with pytest.raises(ApplicationError) as captured:
                await service.apply_ledger_entry(
                    _entry(
                        company_id=data.company_id,
                        actor_id=data.actor_id,
                        product_id=product_id,
                        warehouse_id=warehouse_id,
                        quantity="-1",
                    )
                )
            assert captured.value.code == "INVENTORY_NEGATIVE_BALANCE"
            async with data.database.session() as session:
                assert (
                    await session.scalar(
                        select(InventoryTransactionModel).where(
                            InventoryTransactionModel.company_id == data.company_id
                        )
                    )
                    is None
                )
        finally:
            await _cleanup(manager, data)

    asyncio.run(scenario())


def test_balance_repository_rejects_stale_expected_version() -> None:
    async def scenario() -> None:
        manager, data, product_id, warehouse_id = await _seed_dimensions()
        try:
            entry = _entry(
                company_id=data.company_id,
                actor_id=data.actor_id,
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity="5",
            )
            async with data.database.session() as session, session.begin():
                await InventoryLedgerRepository(session, company_id=data.company_id).append(entry)
                balance = await InventoryBalanceRepository(
                    session, company_id=data.company_id
                ).apply(entry.postings[0])
            async with data.database.session() as first, first.begin():
                repository = InventoryBalanceRepository(first, company_id=data.company_id)
                saved = await repository.save(balance.apply(Decimal("1")), expected_version=1)
                assert saved.version == 2
            async with data.database.session() as second, second.begin():
                with pytest.raises(OptimisticLockError):
                    await InventoryBalanceRepository(second, company_id=data.company_id).save(
                        balance.apply(Decimal("2")), expected_version=1
                    )
        finally:
            await _cleanup(manager, data)

    asyncio.run(scenario())
