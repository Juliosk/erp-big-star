"""Application service for M10 packing operations."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import PermissionCode, SecurityContext
from erp.modules.wms.application.permissions import WMS_PACK_EXECUTE, WmsAuthorization
from erp.modules.wms.domain.package import Package, PackageItem, PackageType
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class CreatePackage:
    company_id: UUID
    package_code: str
    package_type: PackageType = PackageType.CARTON
    wave_id: UUID | None = None
    shipment_id: UUID | None = None
    weight_grams: int | None = None


@dataclass(frozen=True, slots=True)
class AddPackageItem:
    company_id: UUID
    package_id: UUID
    task_id: UUID
    product_id: UUID
    quantity: Decimal
    lot_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PackageCommand:
    company_id: UUID
    package_id: UUID
    expected_version: int


@dataclass(frozen=True, slots=True)
class PackageDetail:
    package: Package
    items: tuple[PackageItem, ...]


class WmsPackingStore(Protocol):
    async def create_package(self, package: Package, actor_id: UUID) -> PackageDetail: ...

    async def get_package(self, company_id: UUID, package_id: UUID) -> PackageDetail | None: ...

    async def add_item(self, command: AddPackageItem, actor_id: UUID) -> PackageDetail: ...

    async def verify_package(self, command: PackageCommand, actor_id: UUID) -> PackageDetail: ...

    async def finalize_package(self, command: PackageCommand, actor_id: UUID) -> PackageDetail: ...


class WmsPackingAuthorizer(Protocol):
    async def require(
        self,
        context: SecurityContext,
        company_id: UUID,
        permission: PermissionCode,
        *,
        write: bool = False,
    ) -> None: ...


class PackingService:
    """Authorize package operations without coupling HTTP to persistence."""

    def __init__(self, store: WmsPackingStore, authorization: WmsAuthorization) -> None:
        self._store = store
        self._authorization: WmsPackingAuthorizer = authorization

    async def create_package(
        self, context: SecurityContext, command: CreatePackage
    ) -> PackageDetail:
        await self._authorization.require(
            context, command.company_id, WMS_PACK_EXECUTE, write=True
        )
        try:
            package = Package.create(
                company_id=command.company_id,
                package_code=command.package_code,
                package_type=command.package_type,
                wave_id=command.wave_id,
                shipment_id=command.shipment_id,
                weight_grams=command.weight_grams,
            )
        except ValueError as error:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid package data.",
                status_code=422,
            ) from error
        return await self._store.create_package(package, context.principal.user_id)

    async def get_package(
        self, context: SecurityContext, company_id: UUID, package_id: UUID
    ) -> PackageDetail:
        await self._authorization.require(context, company_id, WMS_PACK_EXECUTE)
        detail = await self._store.get_package(company_id, package_id)
        if detail is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Package not found.",
                status_code=404,
            )
        return detail

    async def add_item(
        self, context: SecurityContext, command: AddPackageItem
    ) -> PackageDetail:
        await self._authorization.require(
            context, command.company_id, WMS_PACK_EXECUTE, write=True
        )
        return await self._store.add_item(command, context.principal.user_id)

    async def verify_package(
        self, context: SecurityContext, command: PackageCommand
    ) -> PackageDetail:
        await self._authorization.require(
            context, command.company_id, WMS_PACK_EXECUTE, write=True
        )
        return await self._store.verify_package(command, context.principal.user_id)

    async def finalize_package(
        self, context: SecurityContext, command: PackageCommand
    ) -> PackageDetail:
        await self._authorization.require(
            context, command.company_id, WMS_PACK_EXECUTE, write=True
        )
        return await self._store.finalize_package(command, context.principal.user_id)


__all__ = [
    "AddPackageItem",
    "CreatePackage",
    "PackageCommand",
    "PackageDetail",
    "PackingService",
    "WmsPackingStore",
]
