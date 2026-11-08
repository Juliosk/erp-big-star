"""MRP planned-order conversion and material allocation on real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.admin.domain import Branch
from erp.modules.admin.infrastructure import BranchModel, BranchRepository
from erp.modules.inventory.domain import Warehouse
from erp.modules.inventory.infrastructure import (
    InventoryBalanceModel,
    InventoryLotModel,
    InventoryPostingModel,
    InventoryReservationAllocationModel,
    InventoryReservationModel,
    InventoryTransactionModel,
    SessionProductionMaterialReservationGateway,
    WarehouseModel,
    WarehouseRepository,
)
from erp.modules.production.application import (
    ConvertPlannedOrder,
    ExecuteMRP,
    MRPApplicationService,
    MRPEngineeringSnapshot,
    MRPSupplySnapshot,
    PlannedOrderConversionService,
)
from erp.modules.production.domain import (
    BillOfMaterials,
    BomItem,
    EngineeringVersion,
    MRPDemand,
    MRPDemandSource,
    MRPInventoryPosition,
    MRPPlannedOrderType,
    MRPPlanningPolicy,
    MRPSupplyMode,
    ProductionConflictError,
    ProductionQuantity,
    ProductionRouting,
    RoutingOperation,
    ScrapRate,
    UnitOfMeasure,
    WorkCenter,
    WorkCenterCode,
    WorkCenterConstraint,
)
from erp.modules.production.infrastructure import (
    BOMRepository,
    MRPPlannedOrderModel,
    MRPRunHistoryModel,
    MRPRunRepository,
    PostgresProductionEngineeringDirectory,
    ProductionOrderItemPlanModel,
    ProductionOrderModel,
    ProductionOrderOperationExecutionModel,
    ProductionOrderRepository,
    RoutingRepository,
)
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_bom_repository import ProductionFixture, production_fixture
from tests.integration.test_product_persistence import _cnpj

pytestmark = pytest.mark.integration

AS_OF = date(2026, 11, 5)
STARTED_AT = datetime(2026, 11, 5, 9, tzinfo=UTC)
CONVERTED_AT = datetime(2026, 11, 5, 10, tzinfo=UTC)


def _quantity(
    amount: str,
    unit: UnitOfMeasure = UnitOfMeasure.EACH,
) -> ProductionQuantity:
    return ProductionQuantity(Decimal(amount), unit)


@dataclass(frozen=True)
class DemandProvider:
    demand: MRPDemand

    async def demands(
        self,
        *,
        company_id: UUID,
        as_of: date,
        horizon_end: date,
    ) -> tuple[MRPDemand, ...]:
        del company_id, as_of, horizon_end
        return (self.demand,)


@dataclass(frozen=True)
class SupplyProvider:
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
class EngineeringProvider:
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
class ConversionFixture:
    production: ProductionFixture
    run_id: UUID
    manufacture_order_id: UUID
    purchase_order_id: UUID
    warehouse_id: UUID


@asynccontextmanager
async def conversion_fixture(*, stock: str = "10") -> AsyncIterator[ConversionFixture]:
    async with production_fixture() as data:
        version = EngineeringVersion("R1", 1, AS_OF)
        structure = BillOfMaterials(
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
        center_constraint = WorkCenterConstraint(
            data.company_id,
            (WorkCenterCode("MRP-CELL"),),
            frozenset({"ASSEMBLY"}),
        )
        routing = ProductionRouting(
            company_id=data.company_id,
            product_id=data.finished.id,
            version=version,
            operations=(
                RoutingOperation(
                    10,
                    "MRP assembly",
                    center_constraint,
                    Decimal("5"),
                    Decimal("1"),
                ),
            ),
        )
        center = WorkCenter(
            data.company_id,
            WorkCenterCode("MRP-CELL"),
            frozenset({"ASSEMBLY"}),
        )
        branch = Branch.create(
            company_id=data.company_id,
            code=f"MRP{uuid4().hex[:6].upper()}",
            name="MRP conversion branch",
            tax_id=_cnpj(),
            timezone="America/Sao_Paulo",
        )
        warehouse = Warehouse.create(
            company_id=data.company_id,
            branch_id=branch.id,
            code=f"MRP{uuid4().hex[:6].upper()}",
            name="MRP material warehouse",
        )
        async with data.database.session() as session, session.begin():
            await BranchRepository().add(session, branch, actor_id=data.actor_id)
            await WarehouseRepository(session, company_id=data.company_id).add(
                warehouse,
                actor_id=data.actor_id,
            )
            await BOMRepository(session, company_id=data.company_id).add(
                structure,
                actor_id=data.actor_id,
            )
            routings = RoutingRepository(session, company_id=data.company_id)
            await routings.add_work_center(center, actor_id=data.actor_id)
            await routings.add(routing, actor_id=data.actor_id)
            session.add(
                InventoryBalanceModel(
                    id=uuid4(),
                    company_id=data.company_id,
                    product_id=data.raw_material.id,
                    warehouse_id=warehouse.id,
                    location_id=None,
                    lot_id=None,
                    pool_id=None,
                    state="AVAILABLE",
                    quantity=Decimal(stock),
                    version=1,
                )
            )

        demand = MRPDemand(
            company_id=data.company_id,
            source_id=uuid4(),
            source=MRPDemandSource.SALES_ORDER,
            product_id=data.finished.id,
            quantity=_quantity("5"),
            required_on=date(2026, 11, 20),
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
                    _quantity("10", UnitOfMeasure.KILOGRAM),
                    3,
                    _quantity("10", UnitOfMeasure.KILOGRAM),
                ),
            ),
        )
        supply = MRPSupplySnapshot(
            inventory=(
                MRPInventoryPosition(
                    data.company_id,
                    data.finished.id,
                    UnitOfMeasure.EACH,
                ),
                MRPInventoryPosition(
                    data.company_id,
                    data.raw_material.id,
                    UnitOfMeasure.KILOGRAM,
                ),
            )
        )
        run_id = uuid4()
        async with data.database.session() as session, session.begin():
            runs = MRPRunRepository(session, company_id=data.company_id)
            run = await MRPApplicationService(
                demands=DemandProvider(demand),
                supply=SupplyProvider(supply),
                engineering=EngineeringProvider(engineering),
                runs=runs,
                clock=lambda: STARTED_AT,
            ).execute(
                ExecuteMRP(
                    run_id=run_id,
                    company_id=data.company_id,
                    as_of=AS_OF,
                    horizon_end=date(2026, 12, 5),
                    requested_at=STARTED_AT,
                ),
                actor_id=data.actor_id,
            )
        manufacture = next(
            value
            for value in run.plan.planned_orders
            if value.order_type is MRPPlannedOrderType.MANUFACTURE
        )
        purchase = next(
            value
            for value in run.plan.planned_orders
            if value.order_type is MRPPlannedOrderType.PURCHASE
        )
        fixture = ConversionFixture(
            data,
            run_id,
            manufacture.id,
            purchase.id,
            warehouse.id,
        )
        try:
            yield fixture
        finally:
            companies = (data.company_id, data.other_company_id)
            async with data.database.session() as session, session.begin():
                await session.execute(text("SET LOCAL erp.allow_ledger_cleanup = 'on'"))
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
                await session.execute(
                    delete(InventoryReservationAllocationModel).where(
                        InventoryReservationAllocationModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(InventoryReservationModel).where(
                        InventoryReservationModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(ProductionOrderOperationExecutionModel).where(
                        ProductionOrderOperationExecutionModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(ProductionOrderItemPlanModel).where(
                        ProductionOrderItemPlanModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(ProductionOrderModel).where(
                        ProductionOrderModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(AuditEventModel).where(AuditEventModel.company_id.in_(companies))
                )
                await session.execute(
                    delete(OutboxEventModel).where(
                        OutboxEventModel.payload["company_id"].as_string().in_(
                            tuple(str(value) for value in companies)
                        )
                    )
                )
                await session.execute(
                    delete(InventoryPostingModel).where(
                        InventoryPostingModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(InventoryTransactionModel).where(
                        InventoryTransactionModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(InventoryBalanceModel).where(
                        InventoryBalanceModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(InventoryLotModel).where(
                        InventoryLotModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(WarehouseModel).where(WarehouseModel.company_id.in_(companies))
                )
                await session.execute(
                    delete(BranchModel).where(BranchModel.company_id.in_(companies))
                )


def _command(data: ConversionFixture, planned_order_id: UUID) -> ConvertPlannedOrder:
    return ConvertPlannedOrder(
        company_id=data.production.company_id,
        run_id=data.run_id,
        planned_order_id=planned_order_id,
        occurred_at=CONVERTED_AT,
        request_id=uuid4(),
        correlation_id=uuid4(),
    )


def _conversion_service(
    data: ConversionFixture,
    session: AsyncSession,
) -> PlannedOrderConversionService:
    return PlannedOrderConversionService(
        planned_orders=MRPRunRepository(
            session,
            company_id=data.production.company_id,
        ),
        production_orders=ProductionOrderRepository(
            session,
            company_id=data.production.company_id,
        ),
        engineering=PostgresProductionEngineeringDirectory(
            session,
            company_id=data.production.company_id,
        ),
        inventory=SessionProductionMaterialReservationGateway(session),
    )


def test_manufacture_planned_order_converts_atomically_and_replays() -> None:
    async def scenario() -> None:
        async with conversion_fixture() as data:
            command_value = _command(data, data.manufacture_order_id)
            async with data.production.database.session() as session, session.begin():
                result = await _conversion_service(data, session).convert(
                    command_value,
                    actor_id=data.production.actor_id,
                )
                assert result.idempotency_replayed is False
                assert result.production_order.planned_quantity == _quantity("5")
                assert result.production_order.materials[0].planned_quantity == _quantity(
                    "10", UnitOfMeasure.KILOGRAM
                )
                planned = await session.scalar(
                    select(MRPPlannedOrderModel).where(
                        MRPPlannedOrderModel.company_id == data.production.company_id,
                        MRPPlannedOrderModel.mrp_run_id == data.run_id,
                        MRPPlannedOrderModel.id == data.manufacture_order_id,
                    )
                )
                assert planned is not None
                assert (planned.status, planned.version) == ("CONVERTED", 2)
                assert planned.converted_production_order_id == result.production_order.id
                assert planned.material_reservation_id == result.material_reservation_id

            async with data.production.database.session() as session, session.begin():
                replay = await _conversion_service(data, session).convert(
                    command_value,
                    actor_id=data.production.actor_id,
                )
                assert replay.idempotency_replayed is True
                assert replay.production_order.id == result.production_order.id
                assert replay.material_reservation_id == result.material_reservation_id
                assert await session.scalar(
                    select(func.count())
                    .select_from(ProductionOrderModel)
                    .where(ProductionOrderModel.company_id == data.production.company_id)
                ) == 1
                reservation = await session.scalar(
                    select(InventoryReservationModel).where(
                        InventoryReservationModel.company_id == data.production.company_id,
                        InventoryReservationModel.id == result.material_reservation_id,
                    )
                )
                assert reservation is not None
                assert reservation.reference_type == "PRODUCTION_ORDER"
                assert reservation.reference_id == result.production_order.id
                assert await session.scalar(
                    select(func.sum(InventoryReservationAllocationModel.quantity)).where(
                        InventoryReservationAllocationModel.company_id
                        == data.production.company_id,
                        InventoryReservationAllocationModel.reservation_id
                        == result.material_reservation_id,
                    )
                ) == Decimal("10.000000")

    asyncio.run(scenario())


def test_insufficient_inventory_rolls_back_order_reservation_and_conversion() -> None:
    async def scenario() -> None:
        async with conversion_fixture(stock="5") as data:
            command_value = _command(data, data.manufacture_order_id)
            with pytest.raises(ApplicationError) as captured:
                async with data.production.database.session() as session, session.begin():
                    await _conversion_service(data, session).convert(
                        command_value,
                        actor_id=data.production.actor_id,
                    )
            assert captured.value.code == "INVENTORY_RESERVATION_CONFLICT"
            async with data.production.database.session() as session:
                assert await session.scalar(
                    select(func.count())
                    .select_from(ProductionOrderModel)
                    .where(ProductionOrderModel.company_id == data.production.company_id)
                ) == 0
                assert await session.scalar(
                    select(func.count())
                    .select_from(InventoryReservationModel)
                    .where(InventoryReservationModel.company_id == data.production.company_id)
                ) == 0
                planned = await session.scalar(
                    select(MRPPlannedOrderModel).where(
                        MRPPlannedOrderModel.company_id == data.production.company_id,
                        MRPPlannedOrderModel.mrp_run_id == data.run_id,
                        MRPPlannedOrderModel.id == data.manufacture_order_id,
                    )
                )
                assert planned is not None
                assert (planned.status, planned.version) == ("PLANNED", 1)

    asyncio.run(scenario())


def test_purchase_planned_order_cannot_be_converted_to_production() -> None:
    async def scenario() -> None:
        async with (
            conversion_fixture() as data,
            data.production.database.session() as session,
            session.begin(),
        ):
            with pytest.raises(ProductionConflictError, match="MANUFACTURE"):
                await _conversion_service(data, session).convert(
                    _command(data, data.purchase_order_id),
                    actor_id=data.production.actor_id,
                )
            assert await session.scalar(
                select(func.count())
                .select_from(ProductionOrderModel)
                .where(ProductionOrderModel.company_id == data.production.company_id)
            ) == 0

    asyncio.run(scenario())


def test_migration_0054_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    columns = {
                        value["name"]
                        for value in inspector.get_columns(
                            "planned_order", schema="production"
                        )
                    }
                    conversion_columns = {
                        "converted_production_order_id",
                        "material_reservation_id",
                        "converted_at",
                        "converted_by",
                    }
                    assert conversion_columns.issubset(columns) is expected
                    if not expected:
                        return
                    foreign_keys = inspector.get_foreign_keys(
                        "planned_order", schema="production"
                    )
                    assert any(
                        value["constrained_columns"]
                        == ["company_id", "material_reservation_id"]
                        for value in foreign_keys
                    )

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    command.downgrade(configuration, "0053")
    asyncio.run(verify(False))
    command.upgrade(configuration, "head")
    asyncio.run(verify(True))
