"""Transactional PostgreSQL adapter for M10 packing operations."""

from decimal import Decimal
from uuid import UUID

from erp.modules.wms.application.packing import (
    AddPackageItem,
    PackageCommand,
    PackageDetail,
    WmsPackingStore,
)
from erp.modules.wms.domain.package import Package, PackageItem, PackageStatus
from erp.modules.wms.domain.picking import PickingTaskStatus
from erp.modules.wms.infrastructure.repository import WmsRepository
from erp.platform.database import Database
from erp.platform.errors import ApplicationError


class PostgresPackingStore(WmsPackingStore):
    """Persist package flows in one transaction per command."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_package(self, package: Package, actor_id: UUID) -> PackageDetail:
        async with self._database.session() as session, session.begin():
            repository = WmsRepository(session, company_id=package.company_id)
            await repository.add_package(package, actor_id=actor_id)
            return PackageDetail(package, ())

    async def get_package(self, company_id: UUID, package_id: UUID) -> PackageDetail | None:
        async with self._database.session() as session:
            repository = WmsRepository(session, company_id=company_id)
            package = await repository.get_package(package_id)
            if package is None:
                return None
            return PackageDetail(package, await repository.list_package_items(package_id=package.id))

    async def add_item(self, command: AddPackageItem, actor_id: UUID) -> PackageDetail:
        async with self._database.session() as session, session.begin():
            repository = WmsRepository(session, company_id=command.company_id)
            package = await repository.get_package_for_update(command.package_id)
            if package is None:
                raise _not_found("Package")
            if package.status is not PackageStatus.DRAFT:
                raise ApplicationError(
                    code="WMS_PACKAGE_STATUS_CONFLICT",
                    message="Only draft packages can receive items.",
                    status_code=409,
                )
            task = await repository.get_task_for_update(command.task_id)
            if task is None:
                raise _not_found("Picking task")
            if task.product_id != command.product_id or task.lot_id != command.lot_id:
                raise ApplicationError(
                    code="WMS_PACKAGE_ITEM_MISMATCH",
                    message="Package item must match the picking task dimensions.",
                    status_code=409,
                )
            if task.status not in {PickingTaskStatus.IN_PROGRESS, PickingTaskStatus.COMPLETED}:
                raise ApplicationError(
                    code="WMS_PICKING_TASK_NOT_PICKED",
                    message="Picking task must have scanned quantity before packing.",
                    status_code=409,
                )
            packed = Decimal(str(await repository.packed_quantity_for_task(task.id)))
            if packed + command.quantity > task.picked_quantity:
                raise ApplicationError(
                    code="WMS_PACKAGE_OVER_PACK",
                    message="Package item exceeds picked quantity.",
                    status_code=409,
                )
            try:
                item = PackageItem.create(
                    company_id=command.company_id,
                    package_id=command.package_id,
                    task_id=command.task_id,
                    product_id=command.product_id,
                    lot_id=command.lot_id,
                    quantity=command.quantity,
                )
            except ValueError as error:
                raise ApplicationError(
                    code="BUSINESS_VALIDATION_ERROR",
                    message="Invalid package item data.",
                    status_code=422,
                ) from error
            await repository.add_package_item(item, actor_id=actor_id)
            return PackageDetail(
                package,
                await repository.list_package_items(package_id=package.id),
            )

    async def verify_package(self, command: PackageCommand, actor_id: UUID) -> PackageDetail:
        async with self._database.session() as session, session.begin():
            repository = WmsRepository(session, company_id=command.company_id)
            package = await repository.get_package_for_update(command.package_id)
            if package is None:
                raise _not_found("Package")
            items = await repository.list_package_items(package_id=package.id)
            if not items:
                raise ApplicationError(
                    code="WMS_PACKAGE_EMPTY",
                    message="Package requires at least one item before verification.",
                    status_code=409,
                )
            verified = await repository.verify_package(
                package,
                actor_id=actor_id,
                expected_version=command.expected_version,
            )
            return PackageDetail(verified, items)

    async def finalize_package(self, command: PackageCommand, actor_id: UUID) -> PackageDetail:
        async with self._database.session() as session, session.begin():
            repository = WmsRepository(session, company_id=command.company_id)
            package = await repository.get_package_for_update(command.package_id)
            if package is None:
                raise _not_found("Package")
            finalized = await repository.finalize_package(
                package,
                actor_id=actor_id,
                expected_version=command.expected_version,
            )
            return PackageDetail(
                finalized,
                await repository.list_package_items(package_id=finalized.id),
            )


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND",
        message=f"{resource} not found.",
        status_code=404,
    )


__all__ = ["PostgresPackingStore"]
