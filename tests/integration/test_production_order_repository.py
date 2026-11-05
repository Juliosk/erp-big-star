"""Production-order persistence against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect
from sqlalchemy.exc import IntegrityError

from erp.modules.production.domain import (
    BillOfMaterials,
    BomItem,
    EngineeringVersion,
    MaterialRequirement,
    ProductionConflictError,
    ProductionLotTrace,
    ProductionOrder,
    ProductionQuantity,
    ProductionRouting,
    ProductionScopeError,
    ProductionVersionConflictError,
    RoutingOperation,
    ScrapRate,
    UnitOfMeasure,
    WorkCenter,
    WorkCenterCode,
    WorkCenterConstraint,
)
from erp.modules.production.infrastructure import (
    BOMRepository,
    ProductionOrderItemPlanModel,
    ProductionOrderModel,
    ProductionOrderOperationExecutionModel,
    ProductionOrderRepository,
    RoutingRepository,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_bom_repository import ProductionFixture, production_fixture

pytestmark = pytest.mark.integration

CREATED_AT = datetime(2026, 11, 5, 9, tzinfo=UTC)
PLANNED_START = date(2026, 11, 6)


@dataclass(frozen=True)
class ProductionOrderFixture:
    data: ProductionFixture
    bom: BillOfMaterials
    routing: ProductionRouting
    work_center: WorkCenter

    @property
    def company_id(self) -> UUID:
        return self.data.company_id

    @property
    def actor_id(self) -> UUID:
        return self.data.actor_id

    @property
    def database(self) -> Database:
        return self.data.database


def _quantity(
    value: str,
    unit: UnitOfMeasure = UnitOfMeasure.EACH,
) -> ProductionQuantity:
    return ProductionQuantity(Decimal(value), unit)


@asynccontextmanager
async def order_fixture() -> AsyncIterator[ProductionOrderFixture]:
    async with production_fixture() as data:
        version = EngineeringVersion("R1", 1, date(2026, 11, 1))
        constraint = WorkCenterConstraint(
            data.company_id,
            (WorkCenterCode("CUT-01"),),
            frozenset({"LASER"}),
        )
        bom = BillOfMaterials(
            company_id=data.company_id,
            product_id=data.finished.id,
            version=version,
            output_quantity=_quantity("1"),
            items=(
                BomItem(
                    data.raw_material.id,
                    _quantity("2", UnitOfMeasure.KILOGRAM),
                    ScrapRate(),
                ),
            ),
        )
        routing = ProductionRouting(
            company_id=data.company_id,
            product_id=data.finished.id,
            version=version,
            operations=(
                RoutingOperation(
                    10,
                    "Precision cutting",
                    constraint,
                    Decimal("5"),
                    Decimal("0.5"),
                ),
            ),
        )
        work_center = WorkCenter(
            data.company_id,
            WorkCenterCode("CUT-01"),
            frozenset({"LASER", "PRECISION"}),
        )
        async with data.database.session() as session, session.begin():
            await BOMRepository(session, company_id=data.company_id).add(
                bom, actor_id=data.actor_id
            )
            routing_repository = RoutingRepository(session, company_id=data.company_id)
            await routing_repository.add_work_center(
                work_center, actor_id=data.actor_id
            )
            await routing_repository.add(routing, actor_id=data.actor_id)
        fixture = ProductionOrderFixture(data, bom, routing, work_center)
        try:
            yield fixture
        finally:
            company_ids = (data.company_id, data.other_company_id)
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(ProductionOrderOperationExecutionModel).where(
                        ProductionOrderOperationExecutionModel.company_id.in_(
                            company_ids
                        )
                    )
                )
                await session.execute(
                    delete(ProductionOrderItemPlanModel).where(
                        ProductionOrderItemPlanModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(ProductionOrderModel).where(
                        ProductionOrderModel.company_id.in_(company_ids)
                    )
                )


def _order(data: ProductionOrderFixture, *, order_id: UUID | None = None) -> ProductionOrder:
    return ProductionOrder.create(
        company_id=data.company_id,
        order_number=f"OP-{uuid4().hex[:10].upper()}",
        product_id=data.data.finished.id,
        planned_quantity=_quantity("5"),
        planned_start_on=PLANNED_START,
        due_on=date(2026, 11, 10),
        bom=data.bom,
        routing=data.routing,
        material_requirements=(
            MaterialRequirement(
                data.data.raw_material.id,
                _quantity("10", UnitOfMeasure.KILOGRAM),
            ),
        ),
        engineering_approved_at=CREATED_AT,
        engineering_approved_by=data.actor_id,
        created_at=CREATED_AT,
        created_by=data.actor_id,
        order_id=order_id,
    )


async def _save(
    repository: ProductionOrderRepository,
    previous: ProductionOrder,
    current: ProductionOrder,
    actor_id: UUID,
) -> ProductionOrder:
    return await repository.save(
        current,
        actor_id=actor_id,
        expected_version=previous.record_version,
    )


def test_complete_production_order_round_trip() -> None:
    async def scenario() -> None:
        async with order_fixture() as data:
            draft = _order(data)
            async with data.database.session() as session, session.begin():
                repository = ProductionOrderRepository(
                    session, company_id=data.company_id
                )
                assert await repository.add(draft, actor_id=data.actor_id) == draft
                assert await repository.get(draft.id) == draft

                released = draft.release(
                    bom=data.bom,
                    routing=data.routing,
                    actor_id=data.actor_id,
                    occurred_at=CREATED_AT + timedelta(hours=1),
                )
                await _save(repository, draft, released, data.actor_id)
                started = released.start_operation(
                    10,
                    work_center=data.work_center,
                    actor_id=data.actor_id,
                    occurred_at=CREATED_AT + timedelta(hours=2),
                )
                await _save(repository, released, started, data.actor_id)
                consumed = started.record_consumption(
                    ProductionLotTrace(
                        uuid4(),
                        data.data.raw_material.id,
                        _quantity("10", UnitOfMeasure.KILOGRAM),
                    )
                )
                await _save(repository, started, consumed, data.actor_id)
                routed = consumed.complete_operation(
                    10,
                    actor_id=data.actor_id,
                    occurred_at=CREATED_AT + timedelta(hours=3),
                )
                await _save(repository, consumed, routed, data.actor_id)
                completed = routed.complete(
                    output_lots=(
                        ProductionLotTrace(
                            uuid4(),
                            data.data.finished.id,
                            _quantity("4.75"),
                        ),
                    ),
                    actor_id=data.actor_id,
                    occurred_at=CREATED_AT + timedelta(hours=4),
                )
                await _save(repository, routed, completed, data.actor_id)

                assert await repository.get(draft.id) == completed

    asyncio.run(scenario())


def test_optimistic_concurrency_and_tenant_isolation() -> None:
    async def scenario() -> None:
        async with order_fixture() as data:
            draft = _order(data)
            async with data.database.session() as session, session.begin():
                repository = ProductionOrderRepository(
                    session, company_id=data.company_id
                )
                await repository.add(draft, actor_id=data.actor_id)
                changed = draft.reschedule(
                    planned_start_on=date(2026, 11, 7),
                    due_on=date(2026, 11, 11),
                )
                await repository.save(
                    changed,
                    actor_id=data.actor_id,
                    expected_version=1,
                )
                with pytest.raises(ProductionVersionConflictError) as captured:
                    await repository.save(
                        changed,
                        actor_id=data.actor_id,
                        expected_version=1,
                    )
                assert captured.value.code == "VERSION_CONFLICT"
                foreign = ProductionOrderRepository(
                    session, company_id=data.data.other_company_id
                )
                assert await foreign.get(draft.id) is None
                with pytest.raises(ProductionScopeError):
                    await foreign.add(draft, actor_id=data.actor_id)

    asyncio.run(scenario())


def test_repository_never_commits_caller_transaction() -> None:
    async def scenario() -> None:
        async with order_fixture() as data:
            draft = _order(data)
            async with data.database.session() as session:
                transaction = await session.begin()
                await ProductionOrderRepository(
                    session, company_id=data.company_id
                ).add(draft, actor_id=data.actor_id)
                await transaction.rollback()
            async with data.database.session() as session:
                assert (
                    await ProductionOrderRepository(
                        session, company_id=data.company_id
                    ).get(draft.id)
                    is None
                )

    asyncio.run(scenario())


def test_duplicate_order_number_is_translated_to_domain_conflict() -> None:
    async def scenario() -> None:
        async with order_fixture() as data:
            first = _order(data)
            duplicate = replace(first, id=uuid4())
            async with data.database.session() as session, session.begin():
                repository = ProductionOrderRepository(
                    session, company_id=data.company_id
                )
                await repository.add(first, actor_id=data.actor_id)
                nested = await session.begin_nested()
                with pytest.raises(ProductionConflictError):
                    await repository.add(duplicate, actor_id=data.actor_id)
                await nested.rollback()

    asyncio.run(scenario())


def test_repository_contracts_and_update_conflicts_are_explicit() -> None:
    async def scenario() -> None:
        async with order_fixture() as data:
            first = _order(data)
            second = _order(data)
            async with data.database.session() as session, session.begin():
                with pytest.raises(ValueError, match="company UUID"):
                    ProductionOrderRepository(session, company_id=UUID(int=0))
                repository = ProductionOrderRepository(
                    session, company_id=data.company_id
                )
                with pytest.raises(TypeError, match="ProductionOrder"):
                    await repository.add(cast(Any, "bad"), actor_id=data.actor_id)
                with pytest.raises(ValueError, match="record_version one"):
                    await repository.add(
                        replace(first, record_version=2), actor_id=data.actor_id
                    )
                with pytest.raises(ValueError, match="actor_id"):
                    await repository.add(first, actor_id=UUID(int=0))
                with pytest.raises(ValueError, match="order_id"):
                    await repository.get(UUID(int=0))
                await repository.add(first, actor_id=data.actor_id)
                await repository.add(second, actor_id=data.actor_id)
                with pytest.raises(ValueError, match="expected_version"):
                    await repository.save(
                        replace(first, record_version=2),
                        actor_id=data.actor_id,
                        expected_version=0,
                    )
                with pytest.raises(ValueError, match="exactly one"):
                    await repository.save(
                        replace(first, record_version=3),
                        actor_id=data.actor_id,
                        expected_version=1,
                    )
                conflicting = replace(
                    second,
                    order_number=first.order_number,
                    record_version=2,
                )
                nested = await session.begin_nested()
                with pytest.raises(ProductionConflictError):
                    await repository.save(
                        conflicting,
                        actor_id=data.actor_id,
                        expected_version=1,
                    )
                await nested.rollback()

    asyncio.run(scenario())

    original = RuntimeError("driver failure")
    unexpected = IntegrityError("statement", {}, original)
    with pytest.raises(IntegrityError) as captured:
        ProductionOrderRepository._raise_conflict(unexpected)
    assert captured.value is unexpected


def test_migration_0052_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="production"))
                    expected_tables = {
                        "production_order",
                        "production_order_item_plan",
                        "production_order_operation_execution",
                    }
                    assert expected_tables.issubset(tables) is expected
                    if not expected:
                        return
                    foreign_keys = inspector.get_foreign_keys(
                        "production_order_item_plan", schema="production"
                    )
                    assert any(
                        key["constrained_columns"]
                        == ["company_id", "production_order_id"]
                        for key in foreign_keys
                    )
                    indexes = {
                        value["name"]
                        for value in inspector.get_indexes(
                            "production_order", schema="production"
                        )
                    }
                    assert "ix_production_order_company_status_dates" in indexes

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0051")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0052")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")


__all__: list[str] = []
