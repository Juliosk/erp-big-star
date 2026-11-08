"""Shop-floor execution, scrap and real M5 consumption on PostgreSQL."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.inventory.domain import InventoryLot
from erp.modules.inventory.infrastructure import (
    InventoryBalanceModel,
    InventoryPostingModel,
    InventoryReservationAllocationModel,
    InventoryReservationModel,
    InventoryTransactionModel,
    LotRepository,
    SessionProductionMaterialConsumptionGateway,
)
from erp.modules.production.application import (
    CompleteShopFloorOperation,
    MaterialConsumption,
    RecordShopFloorProgress,
    ScrapEntry,
    ShopFloorExecutionService,
    StartShopFloorOperation,
)
from erp.modules.production.domain import ProductionOperationStatus
from erp.modules.production.infrastructure import (
    PostgresProductionEngineeringDirectory,
    ProductionOrderRepository,
    RoutingRepository,
    ScrapRecordModel,
    ShopFloorExecutionRepository,
    ShopFloorOperationLogModel,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_planned_order_conversion import (
    AS_OF,
    ConversionFixture,
    _command,
    _conversion_service,
    conversion_fixture,
)

pytestmark = pytest.mark.integration

STARTED_AT = datetime(2026, 11, 5, 11, tzinfo=UTC)
PROGRESS_AT = datetime(2026, 11, 5, 12, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 11, 5, 13, tzinfo=UTC)


def _service(
    data: ConversionFixture, session: AsyncSession
) -> ShopFloorExecutionService:
    company_id = data.production.company_id
    return ShopFloorExecutionService(
        production_orders=ProductionOrderRepository(session, company_id=company_id),
        work_centers=RoutingRepository(session, company_id=company_id),
        logs=ShopFloorExecutionRepository(session, company_id=company_id),
        inventory=SessionProductionMaterialConsumptionGateway(session),
    )


def test_execution_records_partial_output_scrap_and_real_consumption() -> None:
    async def scenario() -> None:
        async with conversion_fixture() as data:
            lot = InventoryLot.create(
                company_id=data.production.company_id,
                product_id=data.production.raw_material.id,
                code=f"SF-{uuid4().hex[:8]}",
            )
            try:
                async with data.production.database.session() as session, session.begin():
                    await session.execute(
                        delete(InventoryBalanceModel).where(
                            InventoryBalanceModel.company_id == data.production.company_id,
                            InventoryBalanceModel.product_id
                            == data.production.raw_material.id,
                        )
                    )
                    await LotRepository(
                        session, company_id=data.production.company_id
                    ).add(lot, actor_id=data.production.actor_id)
                    session.add(
                        InventoryBalanceModel(
                            id=uuid4(),
                            company_id=data.production.company_id,
                            product_id=data.production.raw_material.id,
                            warehouse_id=data.warehouse_id,
                            location_id=None,
                            lot_id=lot.id,
                            pool_id=None,
                            state="AVAILABLE",
                            quantity=Decimal("10"),
                            version=1,
                        )
                    )

                async with data.production.database.session() as session, session.begin():
                    converted = await _conversion_service(data, session).convert(
                        _command(data, data.manufacture_order_id),
                        actor_id=data.production.actor_id,
                    )
                    engineering = await PostgresProductionEngineeringDirectory(
                        session, company_id=data.production.company_id
                    ).resolve(
                        company_id=data.production.company_id,
                        product_id=data.production.finished.id,
                        version_code="R1",
                        effective_on=AS_OF,
                    )
                    assert engineering is not None
                    released = converted.production_order.release(
                        bom=engineering.bom,
                        routing=engineering.routing,
                        actor_id=data.production.actor_id,
                        occurred_at=STARTED_AT,
                    )
                    await ProductionOrderRepository(
                        session, company_id=data.production.company_id
                    ).save(
                        released,
                        actor_id=data.production.actor_id,
                        expected_version=converted.production_order.record_version,
                    )

                async with data.production.database.session() as session, session.begin():
                    started = await _service(data, session).start(
                        StartShopFloorOperation(
                            company_id=data.production.company_id,
                            production_order_id=released.id,
                            operation_sequence=10,
                            work_center_code="MRP-CELL",
                            expected_version=released.record_version,
                            occurred_at=STARTED_AT,
                            request_id=uuid4(),
                            correlation_id=uuid4(),
                        ),
                        actor_id=data.production.actor_id,
                    )
                    assert started.production_order.operations[0].status is (
                        ProductionOperationStatus.IN_PROGRESS
                    )

                async with data.production.database.session() as session, session.begin():
                    progress = await _service(data, session).report(
                        RecordShopFloorProgress(
                            company_id=data.production.company_id,
                            production_order_id=released.id,
                            operation_sequence=10,
                            expected_version=started.production_order.record_version,
                            occurred_at=PROGRESS_AT,
                            request_id=uuid4(),
                            correlation_id=uuid4(),
                            good_quantity=Decimal("2"),
                            material_consumptions=(
                                MaterialConsumption(
                                    data.production.raw_material.id, Decimal("4")
                                ),
                            ),
                            scraps=(
                                ScrapEntry(
                                    data.production.finished.id,
                                    Decimal("0.5"),
                                    "SETUP_LOSS",
                                    "Perda de regulagem inicial",
                                ),
                            ),
                        ),
                        actor_id=data.production.actor_id,
                    )
                    balance = await session.scalar(
                        select(InventoryBalanceModel).where(
                            InventoryBalanceModel.company_id == data.production.company_id,
                            InventoryBalanceModel.product_id
                            == data.production.raw_material.id,
                            InventoryBalanceModel.lot_id == lot.id,
                        )
                    )
                    allocation = await session.scalar(
                        select(InventoryReservationAllocationModel).where(
                            InventoryReservationAllocationModel.company_id
                            == data.production.company_id,
                            InventoryReservationAllocationModel.reservation_id
                            == converted.material_reservation_id,
                        )
                    )
                    assert balance is not None
                    assert balance.quantity == Decimal("6")
                    assert allocation is not None
                    assert allocation.quantity == Decimal("6")

                async with data.production.database.session() as session, session.begin():
                    completed = await _service(data, session).complete(
                        CompleteShopFloorOperation(
                            company_id=data.production.company_id,
                            production_order_id=released.id,
                            operation_sequence=10,
                            expected_version=progress.production_order.record_version,
                            occurred_at=COMPLETED_AT,
                            request_id=uuid4(),
                            correlation_id=uuid4(),
                            good_quantity=Decimal("3"),
                            material_consumptions=(
                                MaterialConsumption(
                                    data.production.raw_material.id, Decimal("5")
                                ),
                            ),
                            scraps=(
                                ScrapEntry(
                                    data.production.finished.id,
                                    Decimal("0.25"),
                                    "PROCESS_LOSS",
                                    "Perda registrada na conclusão",
                                ),
                            ),
                        ),
                        actor_id=data.production.actor_id,
                    )
                    assert completed.reservation_released is True
                    assert completed.production_order.operations[0].status is (
                        ProductionOperationStatus.COMPLETED
                    )
                    assert completed.production_order.materials[0].actual_amount == Decimal(
                        "9"
                    )
                    balance = await session.scalar(
                        select(InventoryBalanceModel).where(
                            InventoryBalanceModel.company_id == data.production.company_id,
                            InventoryBalanceModel.product_id
                            == data.production.raw_material.id,
                            InventoryBalanceModel.lot_id == lot.id,
                        )
                    )
                    reservation = await session.get(
                        InventoryReservationModel,
                        converted.material_reservation_id,
                    )
                    assert balance is not None
                    assert balance.quantity == Decimal("1")
                    assert reservation is not None
                    assert reservation.status == "RELEASED"
                    assert await session.scalar(
                        select(func.count())
                        .select_from(ShopFloorOperationLogModel)
                        .where(
                            ShopFloorOperationLogModel.company_id
                            == data.production.company_id
                        )
                    ) == 3
                    assert await session.scalar(
                        select(func.sum(ScrapRecordModel.quantity)).where(
                            ScrapRecordModel.company_id == data.production.company_id
                        )
                    ) == Decimal("0.750000")
                    assert await session.scalar(
                        select(func.count())
                        .select_from(InventoryPostingModel)
                        .where(
                            InventoryPostingModel.company_id
                            == data.production.company_id,
                            InventoryPostingModel.transaction_id.in_(
                                select(InventoryTransactionModel.id).where(
                                    InventoryTransactionModel.reference_type
                                    == "PRODUCTION_CONSUMPTION"
                                )
                            ),
                        )
                    ) == 2
            finally:
                async with data.production.database.session() as session, session.begin():
                    await session.execute(
                        delete(ScrapRecordModel).where(
                            ScrapRecordModel.company_id == data.production.company_id
                        )
                    )
                    await session.execute(
                        delete(ShopFloorOperationLogModel).where(
                            ShopFloorOperationLogModel.company_id
                            == data.production.company_id
                        )
                    )

    asyncio.run(scenario())


def test_migration_0055_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="production"))
                    for table in ("shop_floor_operation_log", "scrap_record"):
                        assert (table in tables) is expected

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    command.downgrade(configuration, "0054")
    asyncio.run(verify(False))
    command.upgrade(configuration, "0055")
    asyncio.run(verify(True))
