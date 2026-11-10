"""Commit 213: Sales/WMS fulfillment, labels and marketplace sync proofs."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import Connection, delete, func, inspect, select

from erp.modules.admin.contracts import CompanyAccessService, SecurityContext
from erp.modules.admin.domain import Scope, ScopeType
from erp.modules.marketplace.infrastructure import (
    ChannelOAuthCredentials,
    ChannelOAuthToken,
    HomologationMarketplaceTransport,
    InMemoryChannelCredentialStore,
    MarketplaceGatewayAdapter,
)
from erp.modules.sales.application import (
    SALES_ORDERS_WRITE,
    FulfillSalesOrder,
    SalesAuthorization,
    SalesFulfillmentResult,
    SalesFulfillmentService,
    ShippingLabelRequest,
)
from erp.modules.sales.contracts import ChannelFulfillmentUpdate
from erp.modules.sales.domain import ChannelOrderStatus, Marketplace, ShippingLabel
from erp.modules.sales.infrastructure import (
    MARKETPLACE_FULFILLMENT_SYNC_REQUESTED,
    HomologationShippingGateway,
    PostgresSalesFulfillment,
    SalesFulfillmentLogModel,
    SalesShipmentModel,
)
from erp.modules.sales.infrastructure.channel_model import ChannelSalesOrderModel
from erp.modules.wms.domain import PackageStatus, PackageType, ShipmentStatus
from erp.modules.wms.infrastructure import PackageModel, ShipmentModel
from erp.platform.audit import AuditEventModel
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyRecordModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_multichannel_order_ingestion import (
    CompanyAccessStub,
    IngestionFixture,
    _command,
    _payload,
    ingestion_fixture,
)
from tests.integration.test_multichannel_order_ingestion import (
    _service as ingestion_service,
)

pytestmark = pytest.mark.integration


class BarrierShippingGateway(HomologationShippingGateway):
    def __init__(self) -> None:
        super().__init__()
        self._arrived = 0
        self._release = asyncio.Event()

    async def create_label(
        self, request: ShippingLabelRequest
    ) -> ShippingLabel:
        self._arrived += 1
        if self._arrived == 2:
            self._release.set()
        await self._release.wait()
        return await super().create_label(request)


@dataclass(frozen=True, slots=True)
class FulfillmentFixture:
    ingestion: IngestionFixture
    order_id: UUID
    wms_shipment_id: UUID
    package_id: UUID
    context: SecurityContext


@asynccontextmanager
async def fulfillment_fixture(
    *,
    shipment_status: ShipmentStatus = ShipmentStatus.READY_TO_DISPATCH,
    package_status: PackageStatus = PackageStatus.FINALIZED,
) -> AsyncIterator[FulfillmentFixture]:
    async with ingestion_fixture() as ingestion:
        ingested = await ingestion_service(ingestion).ingest(
            ingestion.context, _command(ingestion, _payload())
        )
        wms_shipment_id = uuid4()
        package_id = uuid4()
        async with ingestion.sales.database.session() as session, session.begin():
            session.add(
                ShipmentModel(
                    id=wms_shipment_id,
                    company_id=ingestion.sales.company_id,
                    shipment_code=f"FUL{uuid4().hex[:12].upper()}",
                    status=shipment_status,
                    carrier_code=None,
                    tracking_code=None,
                    dispatched_at=None,
                    delivered_at=None,
                    version=1,
                    created_by=ingestion.sales.actor_id,
                    updated_by=ingestion.sales.actor_id,
                )
            )
            await session.flush()
            session.add(
                PackageModel(
                    id=package_id,
                    company_id=ingestion.sales.company_id,
                    package_code=f"PKG{uuid4().hex[:12].upper()}",
                    package_type=PackageType.CARTON,
                    status=package_status,
                    wave_id=None,
                    shipment_id=wms_shipment_id,
                    weight_grams=900,
                    version=3,
                    created_by=ingestion.sales.actor_id,
                    updated_by=ingestion.sales.actor_id,
                )
            )
        context = replace(
            ingestion.context,
            permissions=ingestion.context.permissions | {SALES_ORDERS_WRITE},
        )
        resources = FulfillmentFixture(
            ingestion,
            ingested.order.id,
            wms_shipment_id,
            package_id,
            context,
        )
        try:
            yield resources
        finally:
            async with ingestion.sales.database.session() as session, session.begin():
                await session.execute(
                    delete(IdempotencyRecordModel).where(
                        IdempotencyRecordModel.scope.like(
                            f"sales-fulfillment:{ingestion.sales.company_id}:%"
                        )
                    )
                )
                await session.execute(
                    delete(SalesFulfillmentLogModel).where(
                        SalesFulfillmentLogModel.company_id
                        == ingestion.sales.company_id
                    )
                )
                await session.execute(
                    delete(SalesShipmentModel).where(
                        SalesShipmentModel.company_id == ingestion.sales.company_id
                    )
                )
                await session.execute(
                    delete(PackageModel).where(
                        PackageModel.company_id == ingestion.sales.company_id
                    )
                )
                await session.execute(
                    delete(ShipmentModel).where(
                        ShipmentModel.company_id == ingestion.sales.company_id
                    )
                )


def _fulfillment_service(
    data: FulfillmentFixture,
    shipping: HomologationShippingGateway | None = None,
) -> tuple[SalesFulfillmentService, HomologationShippingGateway]:
    gateway = shipping or HomologationShippingGateway()
    service = SalesFulfillmentService(
        PostgresSalesFulfillment(data.ingestion.sales.database),
        SalesAuthorization(cast(CompanyAccessService, CompanyAccessStub())),
        {Marketplace.SHOPEE: gateway},
    )
    return service, gateway


def _fulfill_command(
    data: FulfillmentFixture,
    *,
    company_id: UUID | None = None,
    idempotency_key: str = "commit-213-fulfillment",
) -> FulfillSalesOrder:
    metadata = _command(data.ingestion, _payload()).metadata
    return FulfillSalesOrder(
        company_id=company_id or data.ingestion.sales.company_id,
        order_id=data.order_id,
        wms_shipment_id=data.wms_shipment_id,
        carrier_service="STANDARD",
        expected_order_version=1,
        expected_wms_version=1,
        idempotency_key=idempotency_key,
        metadata=metadata,
    )


def test_fulfillment_dispatches_wms_and_enqueues_channel_status_sync() -> None:
    async def scenario() -> None:
        async with fulfillment_fixture() as data:
            service, shipping = _fulfillment_service(data)
            command = _fulfill_command(data)
            result = await service.fulfill(data.context, command)
            replay = await service.fulfill(data.context, command)

            assert result.order_status is ChannelOrderStatus.SHIPPED
            assert result.order_version == 2
            assert result.shipment.status.value == "DISPATCHED"
            assert result.shipment.version == 2
            assert result.wms_shipment.status == "DISPATCHED"
            assert result.wms_shipment.version == 2
            assert result.wms_shipment.package_ids == (data.package_id,)
            assert replay == replace(result, replayed=True)
            assert shipping.labels_created == 1

            async with data.ingestion.sales.database.session() as session:
                order = await session.get(ChannelSalesOrderModel, data.order_id)
                wms_shipment = await session.get(
                    ShipmentModel, data.wms_shipment_id
                )
                package = await session.get(PackageModel, data.package_id)
                stored = await session.scalar(
                    select(SalesShipmentModel).where(
                        SalesShipmentModel.company_id
                        == data.ingestion.sales.company_id,
                        SalesShipmentModel.sales_order_id == data.order_id,
                    )
                )
                logs = tuple(
                    await session.scalars(
                        select(SalesFulfillmentLogModel)
                        .where(
                            SalesFulfillmentLogModel.company_id
                            == data.ingestion.sales.company_id
                        )
                        .order_by(SalesFulfillmentLogModel.sequence)
                    )
                )
                event = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == result.event_id
                    )
                )
                audit = await session.get(AuditEventModel, result.audit_event_id)
                assert order is not None
                assert order.status == ChannelOrderStatus.SHIPPED
                assert order.version == 2
                assert wms_shipment is not None
                assert wms_shipment.status == ShipmentStatus.DISPATCHED
                assert wms_shipment.tracking_code == result.shipment.label.tracking_code
                assert package is not None
                assert package.status == PackageStatus.DISPATCHED
                assert package.version == 2
                assert stored is not None
                assert stored.version == 2
                assert [value.event_type for value in logs] == [
                    "SEPARATION_CONFIRMED",
                    "LABEL_CREATED",
                    "DISPATCHED",
                    "CHANNEL_SYNC_REQUESTED",
                ]
                assert event is not None
                assert event.event_type == MARKETPLACE_FULFILLMENT_SYNC_REQUESTED
                assert event.payload["payload"]["target_channel_status"] == "SHIPPED"
                assert (
                    event.payload["payload"]["tracking_code"]
                    == result.shipment.label.tracking_code
                )
                assert audit is not None
                assert audit.operation == MARKETPLACE_FULFILLMENT_SYNC_REQUESTED

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("shipment_status", "package_status", "expected_code"),
    [
        (ShipmentStatus.DRAFT, PackageStatus.FINALIZED, "WMS_SHIPMENT_NOT_READY"),
        (
            ShipmentStatus.READY_TO_DISPATCH,
            PackageStatus.VERIFIED,
            "WMS_SHIPMENT_NOT_PACKED",
        ),
    ],
)
def test_unready_or_unpacked_wms_shipment_rolls_back_sales(
    shipment_status: ShipmentStatus,
    package_status: PackageStatus,
    expected_code: str,
) -> None:
    async def scenario() -> None:
        async with fulfillment_fixture(
            shipment_status=shipment_status,
            package_status=package_status,
        ) as data:
            service, _ = _fulfillment_service(data)
            with pytest.raises(ApplicationError) as captured:
                await service.fulfill(data.context, _fulfill_command(data))
            assert captured.value.code == expected_code
            async with data.ingestion.sales.database.session() as session:
                order = await session.get(ChannelSalesOrderModel, data.order_id)
                shipment_count = await session.scalar(
                    select(func.count())
                    .select_from(SalesShipmentModel)
                    .where(
                        SalesShipmentModel.company_id
                        == data.ingestion.sales.company_id
                    )
                )
                event_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(
                        OutboxEventModel.event_type
                        == MARKETPLACE_FULFILLMENT_SYNC_REQUESTED,
                        OutboxEventModel.payload["company_id"].as_string()
                        == str(data.ingestion.sales.company_id),
                    )
                )
                assert order is not None
                assert order.status == ChannelOrderStatus.PAID
                assert order.version == 1
                assert shipment_count == 0
                assert event_count == 0

    asyncio.run(scenario())


def test_fulfillment_hides_known_order_from_another_company() -> None:
    async def scenario() -> None:
        async with fulfillment_fixture() as data:
            foreign_company = data.ingestion.sales.other_company_id
            foreign_context = replace(
                data.context,
                scopes=frozenset({Scope(ScopeType.COMPANY, foreign_company)}),
            )
            service, shipping = _fulfillment_service(data)
            with pytest.raises(ApplicationError) as captured:
                await service.fulfill(
                    foreign_context,
                    _fulfill_command(data, company_id=foreign_company),
                )
            assert captured.value.code == "RESOURCE_NOT_FOUND"
            assert shipping.labels_created == 0

    asyncio.run(scenario())


def test_concurrent_fulfillment_has_one_order_version_winner() -> None:
    async def scenario() -> None:
        async with fulfillment_fixture() as data:
            gateway = BarrierShippingGateway()
            service, _ = _fulfillment_service(data, gateway)
            outcomes = await asyncio.gather(
                service.fulfill(
                    data.context,
                    _fulfill_command(data, idempotency_key="fulfillment-race-a"),
                ),
                service.fulfill(
                    data.context,
                    _fulfill_command(data, idempotency_key="fulfillment-race-b"),
                ),
                return_exceptions=True,
            )
            winners = [
                value
                for value in outcomes
                if isinstance(value, SalesFulfillmentResult)
            ]
            conflicts = [
                value
                for value in outcomes
                if isinstance(value, OptimisticLockError)
                and value.code == "VERSION_CONFLICT"
            ]
            assert len(winners) == 1
            assert len(conflicts) == 1
            assert gateway.labels_created == 1
            async with data.ingestion.sales.database.session() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(SalesShipmentModel)
                        .where(
                            SalesShipmentModel.company_id
                            == data.ingestion.sales.company_id
                        )
                    )
                    == 1
                )

    asyncio.run(scenario())


def test_marketplace_gateway_synchronizes_tracking_for_all_channels() -> None:
    async def scenario() -> None:
        now = datetime(2026, 11, 10, tzinfo=UTC)
        for marketplace in Marketplace:
            credential_reference = f"secret://{marketplace.value.lower()}"
            credentials = InMemoryChannelCredentialStore(
                {
                    credential_reference: ChannelOAuthCredentials(
                        "client",
                        "secret",
                        ChannelOAuthToken(
                            "access",
                            "refresh",
                            now + timedelta(hours=1),
                        ),
                    )
                }
            )
            transport = HomologationMarketplaceTransport({}, now=now)
            gateway = MarketplaceGatewayAdapter(
                marketplace, credentials, transport, now=now
            )
            update = ChannelFulfillmentUpdate(
                company_id=uuid4(),
                account_id=uuid4(),
                marketplace=marketplace,
                external_order_id=f"ORDER-{marketplace.value}",
                status=ChannelOrderStatus.SHIPPED,
                tracking_code="TRK213",
                carrier_code="CHANNEL",
            )
            await gateway.sync_fulfillment(update, credential_reference)
            assert transport.fulfillment_updates == [update]

    asyncio.run(scenario())


def test_migration_0059_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        from erp.platform.config import get_settings
        from erp.platform.database import Database

        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="sales"))
                    assert ("sales_shipment" in tables) is expected
                    assert ("sales_fulfillment_log" in tables) is expected
                    if not expected:
                        return
                    shipment_indexes = {
                        value["name"]
                        for value in inspector.get_indexes(
                            "sales_shipment", schema="sales"
                        )
                    }
                    assert {
                        "ix_sales_shipment_company_status_time",
                        "ix_sales_shipment_company_external",
                    } <= shipment_indexes
                    shipment_uniques = {
                        value["name"]
                        for value in inspector.get_unique_constraints(
                            "sales_shipment", schema="sales"
                        )
                    }
                    assert "uq_sales_shipment_order" in shipment_uniques

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        alembic_command.downgrade(configuration, "0058")
        asyncio.run(verify(False))
        alembic_command.upgrade(configuration, "0059")
        asyncio.run(verify(True))
    finally:
        alembic_command.upgrade(configuration, "head")


__all__: list[str] = []
