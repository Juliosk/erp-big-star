"""Commit 214: route picking, barcode packing and expedition manifesto."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import Connection, delete, func, inspect, select, text

from erp.modules.admin.contracts import CompanyAccessService, SecurityContext
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Scope,
    ScopeType,
)
from erp.modules.inventory.infrastructure import (
    InventoryBalanceModel,
    InventoryPostingModel,
    InventoryTransactionModel,
)
from erp.modules.product.infrastructure import ProductRepository
from erp.modules.product.infrastructure.barcode_model import ProductBarcodeModel
from erp.modules.sales.infrastructure.channel_model import (
    ChannelSalesOrderModel,
    SalesChannelConfigModel,
)
from erp.modules.wms.application import (
    WMS_DISPATCH_EXECUTE,
    WMS_INVENTORY_MOVEMENT,
    WMS_PACK_EXECUTE,
    WMS_PICK_EXECUTE,
    CommandMetadata,
    CreatePickingPackingWave,
    ExecutePickingRoute,
    GenerateExpeditionManifest,
    PickingDemand,
    VerifyPackingScan,
    WmsAuthorization,
    WMSPickingPackingService,
)
from erp.modules.wms.domain import (
    PickingPackingItemStatus,
    PickingPackingWaveStatus,
    ShipmentStatus,
    StorageType,
    WarehouseBin,
)
from erp.modules.wms.infrastructure import (
    PackageItemModel,
    PackageModel,
    PostgresWmsPickingPackingStore,
    ShipmentModel,
    WMSLocationRepository,
    WmsPackingVerificationModel,
    WmsPickingItemModel,
    WmsPickingWaveModel,
)
from erp.platform.errors import ApplicationError
from tests.integration.test_wms_location_repository import (
    WmsLocationFixture,
    _bin,
    wms_location_fixture,
)

pytestmark = pytest.mark.integration
D = Decimal


class CompanyAccessStub:
    async def require_company(
        self, context: SecurityContext, company_id: UUID, *, write: bool = False
    ) -> None:
        assert company_id in {scope.scope_id for scope in context.scopes}
        assert write


@dataclass(frozen=True, slots=True)
class PickingPackingFixture:
    locations: WmsLocationFixture
    bins: tuple[WarehouseBin, WarehouseBin]
    product_ids: tuple[UUID, UUID]
    order_ids: tuple[UUID, UUID]
    shipment_ids: tuple[UUID, UUID]
    barcodes: tuple[str, str]
    context: SecurityContext


@asynccontextmanager
async def picking_packing_fixture() -> AsyncIterator[PickingPackingFixture]:
    async with wms_location_fixture() as locations:
        products = (
            locations.data.product(code=f"PICK{uuid4().hex[:6].upper()}"),
            locations.data.product(code=f"PACK{uuid4().hex[:6].upper()}"),
        )
        bins = (
            _bin(
                locations,
                locations.locations[0],
                zone="PICK",
                aisle="A01",
                bin_code="B01",
                storage_type=StorageType.PICKING,
                occupied_units=1,
                used_weight=D("2"),
                used_volume=D("1"),
            ),
            _bin(
                locations,
                locations.locations[1],
                zone="PICK",
                aisle="A02",
                bin_code="B02",
                storage_type=StorageType.PICKING,
                occupied_units=1,
                used_weight=D("3"),
                used_volume=D("1"),
            ),
        )
        barcodes = "7890000000214", "7890000001211"
        config_id = uuid4()
        account_id = uuid4()
        order_ids = uuid4(), uuid4()
        shipment_ids = uuid4(), uuid4()
        async with locations.database.session() as session, session.begin():
            product_repository = ProductRepository(session, company_id=locations.company_id)
            location_repository = WMSLocationRepository(session, company_id=locations.company_id)
            for product, physical_bin, barcode in zip(products, bins, barcodes, strict=True):
                await product_repository.add(product, actor_id=locations.actor_id)
                await location_repository.add(physical_bin, actor_id=locations.actor_id)
                session.add(
                    ProductBarcodeModel(
                        id=uuid4(),
                        company_id=locations.company_id,
                        product_id=product.id,
                        barcode_type="EAN",
                        barcode=barcode,
                        version=1,
                        created_by=locations.actor_id,
                        updated_by=locations.actor_id,
                    )
                )
                session.add(
                    InventoryBalanceModel(
                        id=uuid4(),
                        company_id=locations.company_id,
                        product_id=product.id,
                        warehouse_id=locations.warehouse.id,
                        location_id=physical_bin.inventory_location_id,
                        lot_id=None,
                        pool_id=None,
                        state="AVAILABLE",
                        quantity=D("1.000000"),
                        version=1,
                    )
                )
            session.add(
                SalesChannelConfigModel(
                    id=config_id,
                    company_id=locations.company_id,
                    account_id=account_id,
                    marketplace="SHOPEE",
                    display_name="Commit 214",
                    credential_reference="secret://commit-214",
                    active=True,
                    version=1,
                    created_by=locations.actor_id,
                    updated_by=locations.actor_id,
                )
            )
            await session.flush()
            for position, (order_id, shipment_id, product) in enumerate(
                zip(order_ids, shipment_ids, products, strict=True), start=1
            ):
                session.add(
                    ChannelSalesOrderModel(
                        id=order_id,
                        company_id=locations.company_id,
                        channel_config_id=config_id,
                        account_id=account_id,
                        marketplace="SHOPEE",
                        external_order_id=f"ORDER-214-{uuid4().hex[:8]}",
                        status="PAID",
                        currency="BRL",
                        merchandise_amount=D("10.00"),
                        freight_amount=D("0.00"),
                        discount_amount=D("0.00"),
                        total_amount=D("10.00"),
                        items=[{"product_id": str(product.id), "quantity": "1"}],
                        source_payload_hash=f"{position}" * 64,
                        version=1,
                        created_by=locations.actor_id,
                        updated_by=locations.actor_id,
                    )
                )
                session.add(
                    ShipmentModel(
                        id=shipment_id,
                        company_id=locations.company_id,
                        shipment_code=f"SHIP214{uuid4().hex[:8].upper()}",
                        status=ShipmentStatus.DRAFT,
                        carrier_code=None,
                        tracking_code=None,
                        dispatched_at=None,
                        delivered_at=None,
                        version=1,
                        created_by=locations.actor_id,
                        updated_by=locations.actor_id,
                    )
                )
        context = SecurityContext(
            principal=AuthenticatedPrincipal(
                locations.actor_id, uuid4(), AuthenticationLevel.LEVEL_2
            ),
            permissions=frozenset(
                {
                    WMS_PICK_EXECUTE,
                    WMS_PACK_EXECUTE,
                    WMS_DISPATCH_EXECUTE,
                    WMS_INVENTORY_MOVEMENT,
                }
            ),
            scopes=frozenset({Scope(ScopeType.COMPANY, locations.company_id)}),
        )
        data = PickingPackingFixture(
            locations,
            bins,
            (products[0].id, products[1].id),
            order_ids,
            shipment_ids,
            barcodes,
            context,
        )
        try:
            yield data
        finally:
            async with locations.database.session() as session, session.begin():
                await session.execute(
                    delete(WmsPackingVerificationModel).where(
                        WmsPackingVerificationModel.company_id == locations.company_id
                    )
                )
                await session.execute(
                    delete(PackageItemModel).where(
                        PackageItemModel.company_id == locations.company_id
                    )
                )
                await session.execute(
                    delete(PackageModel).where(PackageModel.company_id == locations.company_id)
                )
                await session.execute(
                    delete(WmsPickingItemModel).where(
                        WmsPickingItemModel.company_id == locations.company_id
                    )
                )
                await session.execute(
                    delete(WmsPickingWaveModel).where(
                        WmsPickingWaveModel.company_id == locations.company_id
                    )
                )
                await session.execute(
                    delete(ShipmentModel).where(ShipmentModel.company_id == locations.company_id)
                )
                await session.execute(
                    delete(ChannelSalesOrderModel).where(
                        ChannelSalesOrderModel.company_id == locations.company_id
                    )
                )
                await session.execute(
                    delete(SalesChannelConfigModel).where(
                        SalesChannelConfigModel.company_id == locations.company_id
                    )
                )
                await session.execute(
                    delete(ProductBarcodeModel).where(
                        ProductBarcodeModel.company_id == locations.company_id
                    )
                )
                await session.execute(text("SET LOCAL erp.allow_ledger_cleanup = 'on'"))
                await session.execute(
                    delete(InventoryPostingModel).where(
                        InventoryPostingModel.company_id == locations.company_id
                    )
                )
                await session.execute(
                    delete(InventoryTransactionModel).where(
                        InventoryTransactionModel.company_id == locations.company_id
                    )
                )
                await session.execute(
                    delete(InventoryBalanceModel).where(
                        InventoryBalanceModel.company_id == locations.company_id
                    )
                )


def _service(data: PickingPackingFixture) -> WMSPickingPackingService:
    return WMSPickingPackingService(
        PostgresWmsPickingPackingStore(data.locations.database),
        WmsAuthorization(cast(CompanyAccessService, CompanyAccessStub())),
    )


def _metadata() -> CommandMetadata:
    return CommandMetadata(uuid4(), uuid4(), "127.0.0.1")


def _create_command(
    data: PickingPackingFixture, *, company_id: UUID | None = None
) -> CreatePickingPackingWave:
    demands = tuple(
        PickingDemand(
            sales_order_id=data.order_ids[position],
            shipment_id=data.shipment_ids[position],
            product_id=data.product_ids[position],
            bin_id=data.bins[position].inventory_location_id,
            barcode=data.barcodes[position],
            quantity=D("1.000000"),
            units=1,
            unit_weight=D("2.000000") if position == 0 else D("3.000000"),
            unit_volume=D("1.000000000000000000"),
        )
        for position in (1, 0)
    )
    return CreatePickingPackingWave(
        company_id=company_id or data.locations.company_id,
        warehouse_id=data.locations.warehouse.id,
        code=f"WAVE214{uuid4().hex[:8].upper()}",
        demands=demands,
        metadata=_metadata(),
    )


def test_route_picking_packing_manifest_and_m5_issue_are_atomic() -> None:
    async def scenario() -> None:
        async with picking_packing_fixture() as data:
            service = _service(data)
            created = await service.create_wave(data.context, _create_command(data))
            assert created.wave.status is PickingPackingWaveStatus.DRAFT
            assert [item.route_sequence for item in created.items] == [1, 2]
            assert [item.route_address for item in created.items] == sorted(
                item.route_address for item in created.items
            )

            picked = await service.execute_route(
                data.context,
                ExecutePickingRoute(
                    data.locations.company_id,
                    created.wave.id,
                    1,
                    _metadata(),
                ),
            )
            assert picked.wave.status is PickingPackingWaveStatus.PACKING
            assert picked.wave.version == 2
            assert picked.inventory_transaction_id is not None
            assert all(item.status is PickingPackingItemStatus.PICKED for item in picked.items)

            with pytest.raises(ApplicationError) as divergence:
                await service.verify_scan(
                    data.context,
                    VerifyPackingScan(
                        data.locations.company_id,
                        created.wave.id,
                        "7899999999999",
                        D("1.000000"),
                        "wrong-barcode",
                        2,
                        _metadata(),
                    ),
                )
            assert divergence.value.code == "WMS_PACKING_DIVERGENCE"

            first = await service.verify_scan(
                data.context,
                VerifyPackingScan(
                    data.locations.company_id,
                    created.wave.id,
                    picked.items[0].barcode,
                    D("1.000000"),
                    "scan-214-1",
                    2,
                    _metadata(),
                ),
            )
            replay = await service.verify_scan(
                data.context,
                VerifyPackingScan(
                    data.locations.company_id,
                    created.wave.id,
                    picked.items[0].barcode,
                    D("1.000000"),
                    "scan-214-1",
                    2,
                    _metadata(),
                ),
            )
            assert first.detail.wave.version == 3
            assert replay.replayed
            assert replay.verification_id == first.verification_id
            with pytest.raises(ApplicationError) as key_reuse:
                await service.verify_scan(
                    data.context,
                    VerifyPackingScan(
                        data.locations.company_id,
                        created.wave.id,
                        picked.items[1].barcode,
                        D("1.000000"),
                        "scan-214-1",
                        3,
                        _metadata(),
                    ),
                )
            assert key_reuse.value.code == "IDEMPOTENCY_KEY_REUSED"
            second = await service.verify_scan(
                data.context,
                VerifyPackingScan(
                    data.locations.company_id,
                    created.wave.id,
                    picked.items[1].barcode,
                    D("1.000000"),
                    "scan-214-2",
                    3,
                    _metadata(),
                ),
            )
            manifest = await service.generate_manifest(
                data.context,
                GenerateExpeditionManifest(
                    data.locations.company_id,
                    created.wave.id,
                    second.detail.wave.version,
                    _metadata(),
                ),
            )
            assert manifest.detail.wave.status is PickingPackingWaveStatus.MANIFESTED
            assert manifest.detail.wave.version == 5
            assert manifest.manifest.item_count == 2
            assert manifest.manifest.total_quantity == D("2.000000")

            async with data.locations.database.session() as session:
                balances = tuple(
                    await session.scalars(
                        select(InventoryBalanceModel).where(
                            InventoryBalanceModel.company_id == data.locations.company_id,
                            InventoryBalanceModel.product_id.in_(data.product_ids),
                        )
                    )
                )
                bins = tuple(
                    await WMSLocationRepository(
                        session, company_id=data.locations.company_id
                    ).search_bins(warehouse_id=data.locations.warehouse.id)
                )
                shipments = tuple(
                    await session.scalars(
                        select(ShipmentModel).where(
                            ShipmentModel.company_id == data.locations.company_id,
                            ShipmentModel.id.in_(data.shipment_ids),
                        )
                    )
                )
                assert {balance.quantity for balance in balances} == {D("0.000000")}
                assert {
                    value.occupied_units
                    for value in bins
                    if value.inventory_location_id
                    in {item.inventory_location_id for item in data.bins}
                } == {0}
                assert {shipment.status for shipment in shipments} == {
                    ShipmentStatus.READY_TO_DISPATCH
                }
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(PackageModel)
                        .where(PackageModel.company_id == data.locations.company_id)
                    )
                    == 2
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(InventoryPostingModel)
                        .where(
                            InventoryPostingModel.company_id == data.locations.company_id,
                            InventoryPostingModel.transaction_id == picked.inventory_transaction_id,
                        )
                    )
                    == 2
                )

    asyncio.run(scenario())


def test_stale_wave_version_rolls_back_packing_verification() -> None:
    async def scenario() -> None:
        async with picking_packing_fixture() as data:
            service = _service(data)
            created = await service.create_wave(data.context, _create_command(data))
            picked = await service.execute_route(
                data.context,
                ExecutePickingRoute(data.locations.company_id, created.wave.id, 1, _metadata()),
            )
            with pytest.raises(ApplicationError) as conflict:
                await service.verify_scan(
                    data.context,
                    VerifyPackingScan(
                        data.locations.company_id,
                        created.wave.id,
                        picked.items[0].barcode,
                        D("1.000000"),
                        "stale-scan",
                        1,
                        _metadata(),
                    ),
                )
            assert conflict.value.code == "VERSION_CONFLICT"
            async with data.locations.database.session() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(WmsPackingVerificationModel)
                        .where(WmsPackingVerificationModel.company_id == data.locations.company_id)
                    )
                    == 0
                )

    asyncio.run(scenario())


def test_wave_generation_hides_bins_from_another_company() -> None:
    async def scenario() -> None:
        async with picking_packing_fixture() as data:
            foreign_company = data.locations.other_company_id
            foreign_context = replace(
                data.context,
                scopes=frozenset({Scope(ScopeType.COMPANY, foreign_company)}),
            )
            with pytest.raises(ApplicationError) as hidden:
                await _service(data).create_wave(
                    foreign_context,
                    _create_command(data, company_id=foreign_company),
                )
            assert hidden.value.code == "RESOURCE_NOT_FOUND"

    asyncio.run(scenario())


def test_migration_0060_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        from erp.platform.config import get_settings
        from erp.platform.database import Database

        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="wms"))
                    expected_tables = {
                        "wms_picking_wave",
                        "wms_picking_item",
                        "wms_packing_verification",
                    }
                    assert expected_tables.issubset(tables) is expected
                    if not expected:
                        return
                    indexes = {
                        value["name"]
                        for value in inspector.get_indexes("wms_picking_item", schema="wms")
                    }
                    assert "ix_wms_picking_item_cartesian_route" in indexes

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        alembic_command.downgrade(configuration, "0059")
        asyncio.run(verify(False))
        alembic_command.upgrade(configuration, "0060")
        asyncio.run(verify(True))
    finally:
        alembic_command.upgrade(configuration, "head")


__all__: list[str] = []
