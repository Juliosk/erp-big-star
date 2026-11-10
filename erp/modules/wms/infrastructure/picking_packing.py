"""PostgreSQL transaction boundary for route picking and packing."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.domain import (
    InventoryPosting,
    InventoryState,
    InventoryTransaction,
    InventoryTransactionType,
)
from erp.modules.inventory.infrastructure.balance_repository import (
    InventoryBalanceRepository,
)
from erp.modules.inventory.infrastructure.ledger_repository import (
    InventoryLedgerRepository,
)
from erp.modules.product.infrastructure.barcode_model import ProductBarcodeModel
from erp.modules.sales.infrastructure.channel_model import ChannelSalesOrderModel
from erp.modules.wms.application.picking_packing import (
    CreatePickingPackingWave,
    ExecutePickingRoute,
    ExpeditionManifestResult,
    GenerateExpeditionManifest,
    PackingScanResult,
    PickingDemand,
    PickingPackingWaveDetail,
    VerifyPackingScan,
    WmsPickingPackingStore,
)
from erp.modules.wms.domain import (
    ExpeditionManifest,
    PackageStatus,
    PackageType,
    PackingDivergenceError,
    PickingPackingItem,
    PickingPackingItemStatus,
    PickingPackingWave,
    PickingPackingWaveStatus,
    ShipmentStatus,
    WmsPickingPackingError,
)
from erp.modules.wms.infrastructure.location_repository import WMSLocationRepository
from erp.modules.wms.infrastructure.picking_packing_model import (
    WmsPackingVerificationModel,
    WmsPickingItemModel,
    WmsPickingWaveModel,
)
from erp.modules.wms.infrastructure.wms_model import (
    PackageItemModel,
    PackageModel,
    ShipmentModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError

ZERO = Decimal("0")


class PostgresWmsPickingPackingStore(WmsPickingPackingStore):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_wave(
        self, command: CreatePickingPackingWave, actor_id: UUID
    ) -> PickingPackingWaveDetail:
        async with self._database.session() as session, session.begin():
            wave = PickingPackingWave.create(
                company_id=command.company_id,
                warehouse_id=command.warehouse_id,
                code=command.code,
            )
            locations = WMSLocationRepository(session, company_id=command.company_id)
            resolved: list[tuple[str, PickingDemand]] = []
            for demand in command.demands:
                physical_bin = await locations.get(demand.bin_id)
                if (
                    physical_bin is None
                    or physical_bin.address.warehouse_id != command.warehouse_id
                ):
                    raise _not_found("Picking bin")
                await _require_demand_references(session, command.company_id, demand)
                resolved.append((physical_bin.address.code, demand))
            resolved.sort(
                key=lambda value: (
                    value[0],
                    str(value[1].sales_order_id),
                    str(value[1].product_id),
                )
            )
            items = tuple(
                _new_item(
                    wave,
                    demand,
                    route_address=address,
                    route_sequence=sequence,
                )
                for sequence, (address, demand) in enumerate(resolved, start=1)
            )
            session.add(_wave_model(wave, actor_id))
            await _flush_conflict(session, "Picking wave code already exists.")
            session.add_all(_item_model(item, actor_id) for item in items)
            await _flush_conflict(session, "Picking wave code or route already exists.")
            return PickingPackingWaveDetail(wave, items)

    async def execute_route(
        self, command: ExecutePickingRoute, actor_id: UUID
    ) -> PickingPackingWaveDetail:
        async with self._database.session() as session, session.begin():
            wave_model, item_models = await _locked_models(
                session, command.company_id, command.wave_id
            )
            if wave_model.version != command.expected_version:
                raise OptimisticLockError(expected_version=command.expected_version)
            wave = _wave(wave_model)
            items = tuple(_item(model) for model in item_models)
            picked = tuple(item.mark_picked() for item in items)

            locations = WMSLocationRepository(session, company_id=command.company_id)
            for bin_id, bin_items in _by_bin(picked).items():
                physical_bin = await locations.get_for_update(bin_id)
                if physical_bin is None:
                    raise _not_found("Picking bin")
                units = sum(item.units for item in bin_items)
                weight = sum((item.unit_weight * item.units for item in bin_items), ZERO)
                volume = sum((item.unit_volume * item.units for item in bin_items), ZERO)
                placed = physical_bin.plan_pick(
                    units=units,
                    unit_weight=weight / units,
                    unit_volume=volume / units,
                )
                await locations.save(
                    placed,
                    actor_id=actor_id,
                    expected_version=physical_bin.version,
                )

            transaction = InventoryTransaction.create(
                company_id=command.company_id,
                transaction_type=InventoryTransactionType.ISSUE,
                reference_type="WMS_PICKING_WAVE",
                reference_id=wave.id,
                created_by=actor_id,
            )
            postings = tuple(
                InventoryPosting.create(
                    company_id=command.company_id,
                    transaction_id=transaction.id,
                    sequence=sequence,
                    product_id=item.product_id,
                    warehouse_id=item.warehouse_id,
                    location_id=item.bin_id,
                    lot_id=item.lot_id,
                    pool_id=item.pool_id,
                    state=InventoryState.AVAILABLE,
                    quantity_delta=-item.required_quantity,
                )
                for sequence, item in enumerate(picked, start=1)
            )
            entry = InventoryLedgerEntry(transaction, postings)
            await InventoryLedgerRepository(session, company_id=command.company_id).append(entry)
            balances = InventoryBalanceRepository(session, company_id=command.company_id)
            for posting in postings:
                await balances.apply(posting)

            packed_wave = wave.begin_packing(picked)
            _apply_wave(wave_model, packed_wave, actor_id)
            for model, item in zip(item_models, picked, strict=True):
                _apply_item(model, item, actor_id)
            await session.flush()
            return PickingPackingWaveDetail(
                packed_wave, picked, inventory_transaction_id=transaction.id
            )

    async def verify_scan(self, command: VerifyPackingScan, actor_id: UUID) -> PackingScanResult:
        async with self._database.session() as session, session.begin():
            previous = await session.scalar(
                select(WmsPackingVerificationModel).where(
                    WmsPackingVerificationModel.company_id == command.company_id,
                    WmsPackingVerificationModel.wave_id == command.wave_id,
                    WmsPackingVerificationModel.scan_key == command.scan_key,
                )
            )
            if previous is not None:
                if previous.barcode != command.barcode or previous.quantity != command.quantity:
                    raise ApplicationError(
                        code="IDEMPOTENCY_KEY_REUSED",
                        message="The scan key was already used with another payload.",
                        status_code=409,
                    )
                wave_model, item_models = await _models(
                    session, command.company_id, command.wave_id
                )
                return PackingScanResult(
                    PickingPackingWaveDetail(
                        _wave(wave_model), tuple(_item(model) for model in item_models)
                    ),
                    previous.item_id,
                    previous.id,
                    replayed=True,
                )

            wave_model, item_models = await _locked_models(
                session, command.company_id, command.wave_id
            )
            if wave_model.version != command.expected_version:
                raise OptimisticLockError(expected_version=command.expected_version)
            wave = _wave(wave_model)
            if wave.status is not PickingPackingWaveStatus.PACKING:
                raise WmsPickingPackingError("Wave is not in packing verification.")
            candidates = [
                model
                for model in item_models
                if model.barcode == command.barcode
                and model.status != PickingPackingItemStatus.PACKED
            ]
            if not candidates:
                raise PackingDivergenceError(
                    "Barcode is absent or already fully packed in this wave."
                )
            model = candidates[0]
            scanned = _item(model).scan(command.barcode, command.quantity)
            _apply_item(model, scanned, actor_id)
            wave = replace(wave, version=wave.version + 1)
            _apply_wave(wave_model, wave, actor_id)
            sequence = (
                await session.scalar(
                    select(func.count())
                    .select_from(WmsPackingVerificationModel)
                    .where(
                        WmsPackingVerificationModel.company_id == command.company_id,
                        WmsPackingVerificationModel.item_id == scanned.id,
                    )
                )
                or 0
            ) + 1
            verification = WmsPackingVerificationModel(
                id=uuid4(),
                company_id=command.company_id,
                wave_id=command.wave_id,
                item_id=scanned.id,
                scan_key=command.scan_key,
                scan_sequence=sequence,
                barcode=command.barcode,
                quantity=command.quantity,
                verified_at=datetime.now(UTC),
                verified_by=actor_id,
            )
            session.add(verification)
            await _flush_conflict(session, "Packing scan was already processed.")
            current_items = tuple(
                scanned if item.id == scanned.id else item
                for item in (_item(value) for value in item_models)
            )
            return PackingScanResult(
                PickingPackingWaveDetail(wave, current_items),
                scanned.id,
                verification.id,
            )

    async def generate_manifest(
        self, command: GenerateExpeditionManifest, actor_id: UUID
    ) -> ExpeditionManifestResult:
        async with self._database.session() as session, session.begin():
            wave_model, item_models = await _locked_models(
                session, command.company_id, command.wave_id
            )
            if wave_model.version != command.expected_version:
                raise OptimisticLockError(expected_version=command.expected_version)
            wave = _wave(wave_model)
            items = tuple(_item(model) for model in item_models)
            number = f"MNF-{wave.id.hex[:16].upper()}-{wave.version + 1}"
            manifested = wave.generate_manifest(items, number=number)
            _apply_wave(wave_model, manifested, actor_id)
            await _prepare_shipments_and_packages(session, manifested, items, actor_id=actor_id)
            await session.flush()
            manifest = ExpeditionManifest.from_wave(manifested, items)
            return ExpeditionManifestResult(PickingPackingWaveDetail(manifested, items), manifest)


async def _require_demand_references(
    session: AsyncSession, company_id: UUID, demand: PickingDemand
) -> None:
    order = await session.scalar(
        select(ChannelSalesOrderModel).where(
            ChannelSalesOrderModel.company_id == company_id,
            ChannelSalesOrderModel.id == demand.sales_order_id,
            ChannelSalesOrderModel.status == "PAID",
        )
    )
    shipment = await session.scalar(
        select(ShipmentModel).where(
            ShipmentModel.company_id == company_id,
            ShipmentModel.id == demand.shipment_id,
            ShipmentModel.status == ShipmentStatus.DRAFT,
        )
    )
    mapped_barcode = await session.scalar(
        select(ProductBarcodeModel.id).where(
            ProductBarcodeModel.company_id == company_id,
            ProductBarcodeModel.product_id == demand.product_id,
            ProductBarcodeModel.barcode == demand.barcode,
            ProductBarcodeModel.barcode_type == "EAN",
        )
    )
    if order is None:
        raise _not_found("Paid sales order")
    if shipment is None:
        raise _not_found("Draft shipment")
    if mapped_barcode is None:
        raise ApplicationError(
            code="WMS_BARCODE_NOT_MAPPED",
            message="The picking barcode is not mapped to the product.",
            status_code=409,
        )


def _new_item(
    wave: PickingPackingWave,
    demand: PickingDemand,
    *,
    route_address: str,
    route_sequence: int,
) -> PickingPackingItem:
    return PickingPackingItem(
        id=uuid4(),
        company_id=wave.company_id,
        wave_id=wave.id,
        sales_order_id=demand.sales_order_id,
        shipment_id=demand.shipment_id,
        product_id=demand.product_id,
        warehouse_id=wave.warehouse_id,
        bin_id=demand.bin_id,
        lot_id=demand.lot_id,
        pool_id=demand.pool_id,
        barcode=demand.barcode,
        required_quantity=demand.quantity,
        picked_quantity=ZERO,
        packed_quantity=ZERO,
        units=demand.units,
        unit_weight=demand.unit_weight,
        unit_volume=demand.unit_volume,
        route_address=route_address,
        route_sequence=route_sequence,
        status=PickingPackingItemStatus.OPEN,
        version=1,
    )


async def _models(
    session: AsyncSession, company_id: UUID, wave_id: UUID
) -> tuple[WmsPickingWaveModel, list[WmsPickingItemModel]]:
    wave = await session.scalar(
        select(WmsPickingWaveModel).where(
            WmsPickingWaveModel.company_id == company_id,
            WmsPickingWaveModel.id == wave_id,
        )
    )
    if wave is None:
        raise _not_found("Picking wave")
    items = list(
        await session.scalars(
            select(WmsPickingItemModel)
            .where(
                WmsPickingItemModel.company_id == company_id,
                WmsPickingItemModel.wave_id == wave_id,
            )
            .order_by(
                WmsPickingItemModel.route_address,
                WmsPickingItemModel.route_sequence,
            )
        )
    )
    if not items:
        raise WmsPickingPackingError("Picking wave has no route items.")
    return wave, items


async def _locked_models(
    session: AsyncSession, company_id: UUID, wave_id: UUID
) -> tuple[WmsPickingWaveModel, list[WmsPickingItemModel]]:
    wave = await session.scalar(
        select(WmsPickingWaveModel)
        .where(
            WmsPickingWaveModel.company_id == company_id,
            WmsPickingWaveModel.id == wave_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if wave is None:
        raise _not_found("Picking wave")
    items = list(
        await session.scalars(
            select(WmsPickingItemModel)
            .where(
                WmsPickingItemModel.company_id == company_id,
                WmsPickingItemModel.wave_id == wave_id,
            )
            .order_by(
                WmsPickingItemModel.route_address,
                WmsPickingItemModel.route_sequence,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if not items:
        raise WmsPickingPackingError("Picking wave has no route items.")
    return wave, items


async def _prepare_shipments_and_packages(
    session: AsyncSession,
    wave: PickingPackingWave,
    items: tuple[PickingPackingItem, ...],
    *,
    actor_id: UUID,
) -> None:
    for position, shipment_id in enumerate(
        sorted({item.shipment_id for item in items}, key=str), start=1
    ):
        shipment = await session.scalar(
            select(ShipmentModel)
            .where(
                ShipmentModel.company_id == wave.company_id,
                ShipmentModel.id == shipment_id,
            )
            .with_for_update()
        )
        if shipment is None:
            raise _not_found("Shipment")
        if shipment.status != ShipmentStatus.DRAFT:
            raise WmsPickingPackingError("Shipment is no longer available for manifesting.")
        package = PackageModel(
            id=uuid4(),
            company_id=wave.company_id,
            package_code=f"PKG-{wave.id.hex[:12].upper()}-{position}",
            package_type=PackageType.CARTON,
            status=PackageStatus.FINALIZED,
            wave_id=None,
            shipment_id=shipment_id,
            weight_grams=max(
                1,
                int(
                    sum(
                        (
                            item.unit_weight * item.units
                            for item in items
                            if item.shipment_id == shipment_id
                        ),
                        ZERO,
                    )
                    * 1000
                ),
            ),
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add(package)
        await session.flush()
        grouped: dict[tuple[UUID, UUID | None], Decimal] = {}
        for item in items:
            if item.shipment_id == shipment_id:
                key = item.product_id, item.lot_id
                grouped[key] = grouped.get(key, ZERO) + item.required_quantity
        session.add_all(
            PackageItemModel(
                id=uuid4(),
                company_id=wave.company_id,
                package_id=package.id,
                task_id=None,
                product_id=product_id,
                lot_id=lot_id,
                quantity=quantity,
                created_by=actor_id,
            )
            for (product_id, lot_id), quantity in grouped.items()
        )
        shipment.status = ShipmentStatus.READY_TO_DISPATCH
        shipment.version += 1
        shipment.updated_at = datetime.now(UTC)
        shipment.updated_by = actor_id


def _by_bin(items: tuple[PickingPackingItem, ...]) -> dict[UUID, tuple[PickingPackingItem, ...]]:
    grouped: dict[UUID, list[PickingPackingItem]] = {}
    for item in items:
        grouped.setdefault(item.bin_id, []).append(item)
    return {key: tuple(value) for key, value in grouped.items()}


def _wave(model: WmsPickingWaveModel) -> PickingPackingWave:
    return PickingPackingWave(
        id=model.id,
        company_id=model.company_id,
        warehouse_id=model.warehouse_id,
        code=model.code,
        status=PickingPackingWaveStatus(model.status),
        version=model.version,
        manifest_number=model.manifest_number,
        manifested_at=model.manifested_at,
    )


def _item(model: WmsPickingItemModel) -> PickingPackingItem:
    return PickingPackingItem(
        id=model.id,
        company_id=model.company_id,
        wave_id=model.wave_id,
        sales_order_id=model.sales_order_id,
        shipment_id=model.shipment_id,
        product_id=model.product_id,
        warehouse_id=model.warehouse_id,
        bin_id=model.bin_id,
        lot_id=model.lot_id,
        pool_id=model.pool_id,
        barcode=model.barcode,
        required_quantity=model.required_quantity,
        picked_quantity=model.picked_quantity,
        packed_quantity=model.packed_quantity,
        units=model.units,
        unit_weight=model.unit_weight,
        unit_volume=model.unit_volume,
        route_address=model.route_address,
        route_sequence=model.route_sequence,
        status=PickingPackingItemStatus(model.status),
        version=model.version,
    )


def _wave_model(wave: PickingPackingWave, actor_id: UUID) -> WmsPickingWaveModel:
    return WmsPickingWaveModel(
        id=wave.id,
        company_id=wave.company_id,
        warehouse_id=wave.warehouse_id,
        code=wave.code,
        status=wave.status,
        manifest_number=wave.manifest_number,
        manifested_at=wave.manifested_at,
        version=wave.version,
        created_by=actor_id,
        updated_by=actor_id,
    )


def _item_model(item: PickingPackingItem, actor_id: UUID) -> WmsPickingItemModel:
    return WmsPickingItemModel(
        id=item.id,
        company_id=item.company_id,
        wave_id=item.wave_id,
        sales_order_id=item.sales_order_id,
        shipment_id=item.shipment_id,
        product_id=item.product_id,
        warehouse_id=item.warehouse_id,
        bin_id=item.bin_id,
        lot_id=item.lot_id,
        pool_id=item.pool_id,
        barcode=item.barcode,
        required_quantity=item.required_quantity,
        picked_quantity=item.picked_quantity,
        packed_quantity=item.packed_quantity,
        units=item.units,
        unit_weight=item.unit_weight,
        unit_volume=item.unit_volume,
        route_address=item.route_address,
        route_sequence=item.route_sequence,
        status=item.status,
        version=item.version,
        created_by=actor_id,
        updated_by=actor_id,
    )


def _apply_wave(model: WmsPickingWaveModel, wave: PickingPackingWave, actor_id: UUID) -> None:
    model.status = wave.status
    model.manifest_number = wave.manifest_number
    model.manifested_at = wave.manifested_at
    model.version = wave.version
    model.updated_at = datetime.now(UTC)
    model.updated_by = actor_id


def _apply_item(model: WmsPickingItemModel, item: PickingPackingItem, actor_id: UUID) -> None:
    model.picked_quantity = item.picked_quantity
    model.packed_quantity = item.packed_quantity
    model.status = item.status
    model.version = item.version
    model.updated_at = datetime.now(UTC)
    model.updated_by = actor_id


async def _flush_conflict(session: AsyncSession, message: str) -> None:
    try:
        await session.flush()
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) in {"23503", "23505", "23514"}:
            raise ApplicationError(
                code="WMS_PICKING_PACKING_CONFLICT",
                message=message,
                status_code=409,
            ) from error
        raise


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND",
        message=f"{resource} not found.",
        status_code=404,
    )


__all__ = ["PostgresWmsPickingPackingStore"]
