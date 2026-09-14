"""Company-scoped PostgreSQL repositories for M10 WMS aggregates."""

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.inventory.infrastructure.lot_model import InventoryLotModel
from erp.modules.inventory.infrastructure.pool_model import InventoryPoolModel
from erp.modules.inventory.infrastructure.warehouse_model import WarehouseModel
from erp.modules.product.infrastructure.barcode_model import ProductBarcodeModel
from erp.modules.product.infrastructure.product_model import ProductModel
from erp.modules.wms.domain.package import Package, PackageItem, PackageStatus, PackageType
from erp.modules.wms.domain.picking import (
    PickingTask,
    PickingTaskStatus,
    PickingWave,
    PickingWaveStatus,
)
from erp.modules.wms.domain.shipment import Shipment, ShipmentStatus
from erp.modules.wms.infrastructure.wms_model import (
    PackageItemModel,
    PackageModel,
    PickingTaskModel,
    PickingWaveModel,
    ShipmentModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


def _require_company(company_id: UUID) -> None:
    if not isinstance(company_id, UUID):
        raise ValueError("An explicit company UUID is required.")


def _require_actor(actor_id: UUID) -> None:
    if not isinstance(actor_id, UUID):
        raise ValueError("An explicit actor UUID is required.")


def _validate_page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer.")


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND",
        message=f"{resource} not found.",
        status_code=404,
    )


def _outside(resource: str) -> ApplicationError:
    return ApplicationError(
        code="SCOPE_FORBIDDEN",
        message=f"The {resource} is outside the selected company.",
        status_code=403,
    )


def _duplicate(error: IntegrityError, *, resource: str) -> ApplicationError | None:
    if getattr(error.orig, "sqlstate", None) == "23505":
        return ApplicationError(
            code=f"WMS_{resource.upper()}_CONFLICT",
            message=f"This WMS {resource.lower().replace('_', ' ')} already exists.",
            status_code=409,
        )
    return None


def _wave(model: PickingWaveModel) -> PickingWave:
    return PickingWave(
        id=model.id,
        company_id=model.company_id,
        code=model.code,
        status=PickingWaveStatus(model.status),
        source_type=model.source_type,
        source_id=model.source_id,
        warehouse_id=model.warehouse_id,
        released_at=model.released_at,
        released_by=model.released_by,
        version=model.version,
    )


def _task(model: PickingTaskModel) -> PickingTask:
    return PickingTask(
        id=model.id,
        company_id=model.company_id,
        wave_id=model.wave_id,
        sequence=model.sequence,
        product_id=model.product_id,
        warehouse_id=model.warehouse_id,
        lot_id=model.lot_id,
        pool_id=model.pool_id,
        requested_quantity=model.requested_quantity,
        picked_quantity=model.picked_quantity,
        status=PickingTaskStatus(model.status),
        version=model.version,
    )


def _package(model: PackageModel) -> Package:
    return Package(
        id=model.id,
        company_id=model.company_id,
        package_code=model.package_code,
        package_type=PackageType(model.package_type),
        status=PackageStatus(model.status),
        wave_id=model.wave_id,
        shipment_id=model.shipment_id,
        weight_grams=model.weight_grams,
        version=model.version,
    )


def _package_item(model: PackageItemModel) -> PackageItem:
    return PackageItem(
        id=model.id,
        company_id=model.company_id,
        package_id=model.package_id,
        task_id=model.task_id,
        product_id=model.product_id,
        lot_id=model.lot_id,
        quantity=model.quantity,
    )


def _shipment(model: ShipmentModel) -> Shipment:
    return Shipment(
        id=model.id,
        company_id=model.company_id,
        shipment_code=model.shipment_code,
        status=ShipmentStatus(model.status),
        carrier_code=model.carrier_code,
        tracking_code=model.tracking_code,
        dispatched_at=model.dispatched_at,
        delivered_at=model.delivered_at,
        version=model.version,
    )


class WmsRepository:
    """Persistence adapter for WMS records bounded by one selected company."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        _require_company(company_id)
        self._session = session
        self._company_id = company_id

    async def add_wave(self, wave: PickingWave, *, actor_id: UUID) -> None:
        _require_actor(actor_id)
        self._validate_scope(wave.company_id, "picking wave")
        if wave.version != 1 or wave.status is not PickingWaveStatus.DRAFT:
            raise ValueError("A new picking wave must start draft at version one.")
        await self._ensure_warehouse(wave.warehouse_id)
        self._session.add(
            PickingWaveModel(
                id=wave.id,
                company_id=self._company_id,
                code=wave.code,
                status=wave.status,
                source_type=wave.source_type,
                source_id=wave.source_id,
                warehouse_id=wave.warehouse_id,
                released_at=wave.released_at,
                released_by=wave.released_by,
                version=wave.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_unique(resource="PICKING_WAVE")

    async def add_task(self, task: PickingTask, *, actor_id: UUID) -> None:
        _require_actor(actor_id)
        self._validate_scope(task.company_id, "picking task")
        if task.version != 1 or task.status is not PickingTaskStatus.OPEN:
            raise ValueError("A new picking task must start open at version one.")
        if task.picked_quantity != 0:
            raise ValueError("A new picking task cannot start with picked quantity.")
        await self._ensure_wave(task.wave_id)
        await self._ensure_product(task.product_id)
        await self._ensure_warehouse(task.warehouse_id)
        await self._ensure_lot(task.lot_id, product_id=task.product_id)
        await self._ensure_pool(task.pool_id)
        self._session.add(
            PickingTaskModel(
                id=task.id,
                company_id=self._company_id,
                wave_id=task.wave_id,
                sequence=task.sequence,
                product_id=task.product_id,
                warehouse_id=task.warehouse_id,
                lot_id=task.lot_id,
                pool_id=task.pool_id,
                requested_quantity=task.requested_quantity,
                picked_quantity=task.picked_quantity,
                status=task.status,
                version=task.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_unique(resource="PICKING_TASK")

    async def get_task_for_update(self, task_id: UUID) -> PickingTask | None:
        result = await self._session.scalars(
            select(PickingTaskModel)
            .where(
                PickingTaskModel.company_id == self._company_id,
                PickingTaskModel.id == task_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _task(model)

    async def scan_task(
        self,
        task: PickingTask,
        *,
        actor_id: UUID,
        barcode: str,
        quantity: str,
    ) -> PickingTask:
        _require_actor(actor_id)
        self._validate_scope(task.company_id, "picking task")
        await self._ensure_barcode_matches_product(barcode, product_id=task.product_id)
        try:
            scanned = task.scan(quantity)
        except ValueError as error:
            raise ApplicationError(
                code="WMS_PICKING_TASK_OVER_PICK",
                message="Picking task scan exceeds requested quantity.",
                status_code=409,
            ) from error
        result = await self._session.scalars(
            update(PickingTaskModel)
            .where(
                PickingTaskModel.company_id == self._company_id,
                PickingTaskModel.id == task.id,
                PickingTaskModel.version == task.version,
            )
            .values(
                picked_quantity=scanned.picked_quantity,
                status=scanned.status,
                updated_by=actor_id,
                version=PickingTaskModel.version + 1,
            )
            .returning(PickingTaskModel)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        model = result.one_or_none()
        if model is None:
            raise OptimisticLockError(expected_version=task.version)
        await self._session.flush()
        return _task(model)

    async def add_shipment(self, shipment: Shipment, *, actor_id: UUID) -> None:
        _require_actor(actor_id)
        self._validate_scope(shipment.company_id, "shipment")
        if shipment.version != 1 or shipment.status is not ShipmentStatus.DRAFT:
            raise ValueError("A new shipment must start draft at version one.")
        self._session.add(
            ShipmentModel(
                id=shipment.id,
                company_id=self._company_id,
                shipment_code=shipment.shipment_code,
                status=shipment.status,
                carrier_code=shipment.carrier_code,
                tracking_code=shipment.tracking_code,
                dispatched_at=shipment.dispatched_at,
                delivered_at=shipment.delivered_at,
                version=shipment.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_unique(resource="SHIPMENT")

    async def add_package(self, package: Package, *, actor_id: UUID) -> None:
        _require_actor(actor_id)
        self._validate_scope(package.company_id, "package")
        if package.version != 1 or package.status is not PackageStatus.DRAFT:
            raise ValueError("A new package must start draft at version one.")
        if package.wave_id is not None:
            await self._ensure_wave(package.wave_id)
        if package.shipment_id is not None:
            await self._ensure_shipment(package.shipment_id)
        self._session.add(
            PackageModel(
                id=package.id,
                company_id=self._company_id,
                package_code=package.package_code,
                package_type=package.package_type,
                status=package.status,
                wave_id=package.wave_id,
                shipment_id=package.shipment_id,
                weight_grams=package.weight_grams,
                version=package.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_unique(resource="PACKAGE")

    async def add_package_item(self, item: PackageItem, *, actor_id: UUID) -> None:
        _require_actor(actor_id)
        self._validate_scope(item.company_id, "package item")
        await self._ensure_package(item.package_id)
        await self._ensure_product(item.product_id)
        await self._ensure_lot(item.lot_id, product_id=item.product_id)
        self._session.add(
            PackageItemModel(
                id=item.id,
                company_id=self._company_id,
                package_id=item.package_id,
                task_id=item.task_id,
                product_id=item.product_id,
                lot_id=item.lot_id,
                quantity=item.quantity,
                created_by=actor_id,
            )
        )
        await self._flush_unique(resource="PACKAGE_ITEM")

    async def get_wave(self, wave_id: UUID) -> PickingWave | None:
        result = await self._session.scalars(
            select(PickingWaveModel).where(
                PickingWaveModel.company_id == self._company_id,
                PickingWaveModel.id == wave_id,
            ).execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _wave(model)

    async def get_wave_for_update(self, wave_id: UUID) -> PickingWave | None:
        result = await self._session.scalars(
            select(PickingWaveModel)
            .where(
                PickingWaveModel.company_id == self._company_id,
                PickingWaveModel.id == wave_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _wave(model)

    async def release_wave(
        self,
        wave: PickingWave,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> PickingWave:
        _require_actor(actor_id)
        self._validate_scope(wave.company_id, "picking wave")
        if wave.version != expected_version:
            raise OptimisticLockError(expected_version=expected_version)
        try:
            released = wave.release(actor_id=actor_id)
        except ValueError as error:
            raise ApplicationError(
                code="WMS_PICKING_WAVE_STATUS_CONFLICT",
                message="Picking wave cannot be released.",
                status_code=409,
            ) from error
        result = await self._session.scalars(
            update(PickingWaveModel)
            .where(
                PickingWaveModel.company_id == self._company_id,
                PickingWaveModel.id == wave.id,
                PickingWaveModel.version == expected_version,
                PickingWaveModel.status == PickingWaveStatus.DRAFT,
            )
            .values(
                status=released.status,
                released_at=released.released_at,
                released_by=released.released_by,
                updated_by=actor_id,
                version=PickingWaveModel.version + 1,
            )
            .returning(PickingWaveModel)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        model = result.one_or_none()
        if model is None:
            raise OptimisticLockError(expected_version=expected_version)
        await self._session.flush()
        return _wave(model)

    async def list_waves(
        self,
        *,
        status: PickingWaveStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PickingWave, ...]:
        _validate_page(limit, offset)
        statement = select(PickingWaveModel).where(PickingWaveModel.company_id == self._company_id)
        if status is not None:
            statement = statement.where(PickingWaveModel.status == status)
        result = await self._session.scalars(
            statement.order_by(PickingWaveModel.code, PickingWaveModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_wave(model) for model in result)

    async def list_tasks(self, *, wave_id: UUID) -> tuple[PickingTask, ...]:
        result = await self._session.scalars(
            select(PickingTaskModel)
            .where(
                PickingTaskModel.company_id == self._company_id,
                PickingTaskModel.wave_id == wave_id,
            )
            .order_by(PickingTaskModel.sequence, PickingTaskModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_task(model) for model in result)

    async def get_shipment(self, shipment_id: UUID) -> Shipment | None:
        result = await self._session.scalars(
            select(ShipmentModel).where(
                ShipmentModel.company_id == self._company_id,
                ShipmentModel.id == shipment_id,
            ).execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _shipment(model)

    async def get_package(self, package_id: UUID) -> Package | None:
        result = await self._session.scalars(
            select(PackageModel).where(
                PackageModel.company_id == self._company_id,
                PackageModel.id == package_id,
            ).execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _package(model)

    async def get_package_for_update(self, package_id: UUID) -> Package | None:
        result = await self._session.scalars(
            select(PackageModel)
            .where(
                PackageModel.company_id == self._company_id,
                PackageModel.id == package_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _package(model)

    async def list_package_items(self, *, package_id: UUID) -> tuple[PackageItem, ...]:
        result = await self._session.scalars(
            select(PackageItemModel)
            .where(
                PackageItemModel.company_id == self._company_id,
                PackageItemModel.package_id == package_id,
            )
            .order_by(PackageItemModel.created_at, PackageItemModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_package_item(model) for model in result)

    async def packed_quantity_for_task(self, task_id: UUID) -> Decimal:
        total = await self._session.scalar(
            select(func.coalesce(func.sum(PackageItemModel.quantity), 0)).where(
                PackageItemModel.company_id == self._company_id,
                PackageItemModel.task_id == task_id,
            )
        )
        return Decimal(str(total))

    async def verify_package(
        self,
        package: Package,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> Package:
        _require_actor(actor_id)
        self._validate_scope(package.company_id, "package")
        if package.version != expected_version:
            raise OptimisticLockError(expected_version=expected_version)
        try:
            verified = package.verify()
        except ValueError as error:
            raise ApplicationError(
                code="WMS_PACKAGE_STATUS_CONFLICT",
                message="Package cannot be verified.",
                status_code=409,
            ) from error
        return await self._update_package_status(
            verified,
            actor_id=actor_id,
            expected_version=expected_version,
            required_status=PackageStatus.DRAFT,
        )

    async def finalize_package(
        self,
        package: Package,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> Package:
        _require_actor(actor_id)
        self._validate_scope(package.company_id, "package")
        if package.version != expected_version:
            raise OptimisticLockError(expected_version=expected_version)
        try:
            finalized = package.finalize()
        except ValueError as error:
            raise ApplicationError(
                code="WMS_PACKAGE_STATUS_CONFLICT",
                message="Package cannot be finalized.",
                status_code=409,
            ) from error
        return await self._update_package_status(
            finalized,
            actor_id=actor_id,
            expected_version=expected_version,
            required_status=PackageStatus.VERIFIED,
        )

    async def _update_package_status(
        self,
        package: Package,
        *,
        actor_id: UUID,
        expected_version: int,
        required_status: PackageStatus,
    ) -> Package:
        result = await self._session.scalars(
            update(PackageModel)
            .where(
                PackageModel.company_id == self._company_id,
                PackageModel.id == package.id,
                PackageModel.version == expected_version,
                PackageModel.status == required_status,
            )
            .values(
                status=package.status,
                updated_by=actor_id,
                version=PackageModel.version + 1,
            )
            .returning(PackageModel)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        model = result.one_or_none()
        if model is None:
            raise OptimisticLockError(expected_version=expected_version)
        await self._session.flush()
        return _package(model)

    async def _flush_unique(self, *, resource: str) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            conflict = _duplicate(error, resource=resource)
            if conflict is not None:
                raise conflict from error
            raise

    def _validate_scope(self, company_id: UUID, resource: str) -> None:
        if company_id != self._company_id:
            raise _outside(resource)

    async def _exists(self, model: Any, model_id: UUID) -> bool:
        value = await self._session.scalar(
            select(1)
            .select_from(model)
            .where(model.company_id == self._company_id, model.id == model_id)
        )
        return value is not None

    async def _ensure_wave(self, wave_id: UUID) -> None:
        if not await self._exists(PickingWaveModel, wave_id):
            raise _not_found("Picking wave")

    async def _ensure_product(self, product_id: UUID) -> None:
        if not await self._exists(ProductModel, product_id):
            raise _not_found("Product")

    async def _ensure_barcode_matches_product(self, barcode: str, *, product_id: UUID) -> None:
        normalized = barcode.strip().upper()
        if not normalized:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid picking scan data.",
                status_code=422,
            )
        row = await self._session.scalar(
            select(ProductBarcodeModel).where(
                ProductBarcodeModel.company_id == self._company_id,
                ProductBarcodeModel.barcode == normalized,
            )
        )
        if row is None or row.product_id != product_id:
            raise ApplicationError(
                code="WMS_BARCODE_MISMATCH",
                message="Scanned barcode does not match the picking task product.",
                status_code=409,
            )

    async def _ensure_warehouse(self, warehouse_id: UUID | None) -> None:
        if warehouse_id is not None and not await self._exists(WarehouseModel, warehouse_id):
            raise _not_found("Warehouse")

    async def _ensure_lot(self, lot_id: UUID | None, *, product_id: UUID) -> None:
        if lot_id is None:
            return
        result = await self._session.scalars(
            select(InventoryLotModel).where(
                InventoryLotModel.company_id == self._company_id,
                InventoryLotModel.id == lot_id,
            )
        )
        lot = result.one_or_none()
        if lot is None:
            raise _not_found("Inventory lot")
        if lot.product_id != product_id:
            raise ApplicationError(
                code="WMS_LOT_PRODUCT_MISMATCH",
                message="Inventory lot belongs to another product.",
                status_code=409,
            )

    async def _ensure_pool(self, pool_id: UUID | None) -> None:
        if pool_id is not None and not await self._exists(InventoryPoolModel, pool_id):
            raise _not_found("Inventory pool")

    async def _ensure_shipment(self, shipment_id: UUID) -> None:
        if not await self._exists(ShipmentModel, shipment_id):
            raise _not_found("Shipment")

    async def _ensure_package(self, package_id: UUID) -> None:
        if not await self._exists(PackageModel, package_id):
            raise _not_found("Package")

__all__ = [
    "WmsRepository",
    "_package",
    "_package_item",
    "_shipment",
    "_task",
    "_wave",
]
