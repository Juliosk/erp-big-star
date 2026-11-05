"""Transactional MRP orchestration and persistence against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect, select

from erp.modules.production.application import (
    ExecuteMRP,
    MRPApplicationService,
    MRPEngineeringSnapshot,
    MRPSupplySnapshot,
)
from erp.modules.production.domain import (
    BillOfMaterials,
    BomItem,
    EngineeringVersion,
    InvalidProductionValueError,
    MRPDemand,
    MRPDemandSource,
    MRPInventoryPosition,
    MRPPlanningPolicy,
    MRPScheduledReceipt,
    MRPScheduledReceiptType,
    MRPSupplyMode,
    ProductionConflictError,
    ProductionQuantity,
    ProductionScopeError,
    ScrapRate,
    UnitOfMeasure,
)
from erp.modules.production.infrastructure import (
    MRPPlannedOrderModel,
    MRPRunHistoryModel,
    MRPRunRepository,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_bom_repository import ProductionFixture, production_fixture

pytestmark = pytest.mark.integration

AS_OF = date(2026, 11, 5)
HORIZON_END = date(2026, 12, 5)
STARTED_AT = datetime(2026, 11, 5, 9, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 11, 5, 9, 0, 2, tzinfo=UTC)


def _quantity(
    value: str,
    unit: UnitOfMeasure = UnitOfMeasure.EACH,
) -> ProductionQuantity:
    return ProductionQuantity(Decimal(value), unit)


@dataclass(frozen=True)
class FixedDemands:
    values: tuple[MRPDemand, ...]

    async def demands(
        self,
        *,
        company_id: UUID,
        as_of: date,
        horizon_end: date,
    ) -> tuple[MRPDemand, ...]:
        assert (company_id, as_of, horizon_end) == (
            self.values[0].company_id,
            AS_OF,
            HORIZON_END,
        )
        return self.values


@dataclass(frozen=True)
class FixedSupply:
    value: MRPSupplySnapshot

    async def supply(
        self,
        *,
        company_id: UUID,
        as_of: date,
        horizon_end: date,
    ) -> MRPSupplySnapshot:
        del company_id, as_of, horizon_end
        return self.value


@dataclass(frozen=True)
class FixedEngineering:
    value: MRPEngineeringSnapshot

    async def engineering(
        self,
        *,
        company_id: UUID,
        as_of: date,
        horizon_end: date,
    ) -> MRPEngineeringSnapshot:
        del company_id, as_of, horizon_end
        return self.value


@dataclass(frozen=True)
class MRPFixture:
    production: ProductionFixture
    demand: MRPDemand
    supply: MRPSupplySnapshot
    engineering: MRPEngineeringSnapshot


@asynccontextmanager
async def mrp_fixture() -> AsyncIterator[MRPFixture]:
    async with production_fixture() as data:
        structure = BillOfMaterials(
            company_id=data.company_id,
            product_id=data.finished.id,
            version=EngineeringVersion("R1", 1, AS_OF),
            output_quantity=_quantity("1"),
            items=(
                BomItem(
                    data.raw_material.id,
                    _quantity("2", UnitOfMeasure.KILOGRAM),
                    ScrapRate(),
                ),
            ),
        )
        demand = MRPDemand(
            company_id=data.company_id,
            source_id=uuid4(),
            source=MRPDemandSource.SALES_ORDER,
            product_id=data.finished.id,
            quantity=_quantity("5"),
            required_on=date(2026, 11, 20),
        )
        supply = MRPSupplySnapshot(
            inventory=(
                MRPInventoryPosition(
                    data.company_id,
                    data.finished.id,
                    UnitOfMeasure.EACH,
                    on_hand=Decimal("1"),
                ),
                MRPInventoryPosition(
                    data.company_id,
                    data.raw_material.id,
                    UnitOfMeasure.KILOGRAM,
                    on_hand=Decimal("2"),
                ),
            ),
            scheduled_receipts=(
                MRPScheduledReceipt(
                    data.company_id,
                    uuid4(),
                    MRPScheduledReceiptType.PURCHASE_ORDER,
                    data.raw_material.id,
                    _quantity("1", UnitOfMeasure.KILOGRAM),
                    date(2026, 11, 17),
                ),
            ),
        )
        engineering = MRPEngineeringSnapshot(
            boms=(structure,),
            policies=(
                MRPPlanningPolicy(
                    data.company_id,
                    data.finished.id,
                    MRPSupplyMode.MAKE,
                    _quantity("5"),
                    2,
                    _quantity("5"),
                ),
                MRPPlanningPolicy(
                    data.company_id,
                    data.raw_material.id,
                    MRPSupplyMode.BUY,
                    _quantity("5", UnitOfMeasure.KILOGRAM),
                    3,
                    _quantity("5", UnitOfMeasure.KILOGRAM),
                ),
            ),
        )
        fixture = MRPFixture(data, demand, supply, engineering)
        try:
            yield fixture
        finally:
            companies = (data.company_id, data.other_company_id)
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(MRPPlannedOrderModel).where(
                        MRPPlannedOrderModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(MRPRunHistoryModel).where(
                        MRPRunHistoryModel.company_id.in_(companies)
                    )
                )


def _command(company_id: UUID, *, run_id: UUID | None = None) -> ExecuteMRP:
    return ExecuteMRP(
        run_id=run_id or uuid4(),
        company_id=company_id,
        as_of=AS_OF,
        horizon_end=HORIZON_END,
        requested_at=STARTED_AT,
    )


def _service(data: MRPFixture, repository: MRPRunRepository) -> MRPApplicationService:
    return MRPApplicationService(
        demands=FixedDemands((data.demand,)),
        supply=FixedSupply(data.supply),
        engineering=FixedEngineering(data.engineering),
        runs=repository,
        clock=lambda: COMPLETED_AT,
    )


def test_mrp_execution_is_persisted_atomically_and_reproducibly() -> None:
    async def scenario() -> None:
        async with mrp_fixture() as data:
            command_value = _command(data.production.company_id)
            async with data.production.database.session() as session, session.begin():
                repository = MRPRunRepository(
                    session, company_id=data.production.company_id
                )
                run = await _service(data, repository).execute(
                    command_value,
                    actor_id=data.production.actor_id,
                )
                assert run.plan.demands == (data.demand,)
                assert [order.order_type.value for order in run.plan.planned_orders] == [
                    "MANUFACTURE",
                    "PURCHASE",
                ]
                assert [order.quantity.amount for order in run.plan.planned_orders] == [
                    Decimal("5.000000"),
                    Decimal("10.000000"),
                ]
                assert await repository.get(run.id) == run
                assert await repository.planned_orders(run.id) == run.plan.planned_orders

                header = await session.scalar(
                    select(MRPRunHistoryModel).where(MRPRunHistoryModel.id == run.id)
                )
                assert header is not None
                assert (header.demand_count, header.planned_order_count) == (1, 2)
                assert header.engine_version == "MRP_V1"

            async with data.production.database.session() as session, session.begin():
                repository = MRPRunRepository(
                    session, company_id=data.production.company_id
                )
                replay = await _service(data, repository).execute(
                    _command(data.production.company_id),
                    actor_id=data.production.actor_id,
                )
                assert [value.id for value in replay.plan.planned_orders] == [
                    value.id for value in run.plan.planned_orders
                ]

    asyncio.run(scenario())


def test_repository_is_tenant_bound_and_never_commits_caller_transaction() -> None:
    async def scenario() -> None:
        async with mrp_fixture() as data:
            command_value = _command(data.production.company_id)
            async with data.production.database.session() as session:
                transaction = await session.begin()
                repository = MRPRunRepository(
                    session, company_id=data.production.company_id
                )
                run = await _service(data, repository).execute(
                    command_value,
                    actor_id=data.production.actor_id,
                )
                foreign = MRPRunRepository(
                    session, company_id=data.production.other_company_id
                )
                assert await foreign.get(run.id) is None
                with pytest.raises(ProductionScopeError):
                    await foreign.add(run, actor_id=data.production.actor_id)
                await transaction.rollback()

            async with data.production.database.session() as session:
                assert (
                    await MRPRunRepository(
                        session, company_id=data.production.company_id
                    ).get(command_value.run_id)
                    is None
                )

    asyncio.run(scenario())


def test_duplicate_run_and_application_contracts_fail_closed() -> None:
    async def scenario() -> None:
        async with mrp_fixture() as data:
            command_value = _command(data.production.company_id)
            async with data.production.database.session() as session, session.begin():
                repository = MRPRunRepository(
                    session, company_id=data.production.company_id
                )
                service = _service(data, repository)
                run = await service.execute(
                    command_value,
                    actor_id=data.production.actor_id,
                )
                nested = await session.begin_nested()
                with pytest.raises(ProductionConflictError):
                    await repository.add(run, actor_id=data.production.actor_id)
                await nested.rollback()

                with pytest.raises(InvalidProductionValueError, match="command"):
                    await service.execute(
                        cast(Any, "invalid"),
                        actor_id=data.production.actor_id,
                    )
                with pytest.raises(InvalidProductionValueError, match="actor_id"):
                    await service.execute(command_value, actor_id=UUID(int=0))
                with pytest.raises(ValueError, match="company UUID"):
                    MRPRunRepository(session, company_id=UUID(int=0))
                with pytest.raises(ValueError, match="run_id"):
                    await repository.get(UUID(int=0))
                with pytest.raises(TypeError, match="MRPRun"):
                    await repository.add(
                        cast(Any, "invalid"), actor_id=data.production.actor_id
                    )

    asyncio.run(scenario())


def test_provider_values_outside_requested_horizon_are_rejected() -> None:
    async def scenario() -> None:
        async with mrp_fixture() as data:
            late = MRPDemand(
                company_id=data.production.company_id,
                source_id=uuid4(),
                source=MRPDemandSource.FORECAST,
                product_id=data.production.finished.id,
                quantity=_quantity("1"),
                required_on=HORIZON_END.replace(year=2027),
            )
            async with data.production.database.session() as session, session.begin():
                service = MRPApplicationService(
                    demands=FixedDemands((late,)),
                    supply=FixedSupply(data.supply),
                    engineering=FixedEngineering(data.engineering),
                    runs=MRPRunRepository(
                        session, company_id=data.production.company_id
                    ),
                    clock=lambda: COMPLETED_AT,
                )
                with pytest.raises(InvalidProductionValueError, match="horizon"):
                    await service.execute(
                        _command(data.production.company_id),
                        actor_id=data.production.actor_id,
                    )

    asyncio.run(scenario())


def test_migration_0053_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="production"))
                    assert ({"mrp_run_history", "planned_order"} <= tables) is expected
                    if not expected:
                        return
                    foreign_keys = inspector.get_foreign_keys(
                        "planned_order", schema="production"
                    )
                    assert any(
                        key["constrained_columns"] == ["company_id", "mrp_run_id"]
                        for key in foreign_keys
                    )
                    indexes = {
                        value["name"]
                        for value in inspector.get_indexes(
                            "planned_order", schema="production"
                        )
                    }
                    assert "ix_planned_order_company_status_dates" in indexes

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    command.downgrade(configuration, "0052")
    asyncio.run(verify(False))
    command.upgrade(configuration, "0053")
    asyncio.run(verify(True))
    command.upgrade(configuration, "head")
