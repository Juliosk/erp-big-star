"""Authorized read services and ports for physical inventory records."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.application.permissions import (
    INVENTORY_LOCATION_READ,
    INVENTORY_LOT_READ,
    INVENTORY_POOL_READ,
    INVENTORY_WAREHOUSE_READ,
    InventoryAuthorization,
)
from erp.modules.inventory.domain import (
    InventoryLot,
    InventoryLotStatus,
    InventoryPool,
    Warehouse,
    WarehouseLocation,
)
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class InventoryPage[T]:
    items: tuple[T, ...]
    page: int
    page_size: int
    has_more: bool


class InventoryDirectory(Protocol):
    async def list_warehouses(
        self, company_id: UUID, *, page: int, page_size: int, active: bool | None
    ) -> InventoryPage[Warehouse]: ...

    async def get_warehouse(self, company_id: UUID, warehouse_id: UUID) -> Warehouse | None: ...

    async def list_locations(
        self,
        company_id: UUID,
        *,
        warehouse_id: UUID | None,
        page: int,
        page_size: int,
        active: bool | None,
    ) -> InventoryPage[WarehouseLocation]: ...

    async def get_location(
        self, company_id: UUID, location_id: UUID
    ) -> WarehouseLocation | None: ...

    async def list_pools(
        self, company_id: UUID, *, page: int, page_size: int, active: bool | None
    ) -> InventoryPage[InventoryPool]: ...

    async def get_pool(self, company_id: UUID, pool_id: UUID) -> InventoryPool | None: ...

    async def list_lots(
        self,
        company_id: UUID,
        *,
        product_id: UUID | None,
        status: InventoryLotStatus | None,
        page: int,
        page_size: int,
    ) -> InventoryPage[InventoryLot]: ...

    async def get_lot(self, company_id: UUID, lot_id: UUID) -> InventoryLot | None: ...


class InventoryQueries:
    """Authorize first, then delegate only company-scoped reads."""

    def __init__(
        self, directory: InventoryDirectory, authorization: InventoryAuthorization
    ) -> None:
        self._directory = directory
        self._authorization = authorization

    async def list_warehouses(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        active: bool | None = None,
    ) -> InventoryPage[Warehouse]:
        await self._authorization.require(context, company_id, INVENTORY_WAREHOUSE_READ)
        _validate_page(page, page_size)
        return await self._directory.list_warehouses(
            company_id, page=page, page_size=page_size, active=active
        )

    async def get_warehouse(
        self, context: SecurityContext, company_id: UUID, warehouse_id: UUID
    ) -> Warehouse:
        await self._authorization.require(context, company_id, INVENTORY_WAREHOUSE_READ)
        item = await self._directory.get_warehouse(company_id, warehouse_id)
        if item is None:
            raise _not_found("Warehouse")
        return item

    async def list_locations(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        warehouse_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
        active: bool | None = None,
    ) -> InventoryPage[WarehouseLocation]:
        await self._authorization.require(context, company_id, INVENTORY_LOCATION_READ)
        _validate_page(page, page_size)
        return await self._directory.list_locations(
            company_id,
            warehouse_id=warehouse_id,
            page=page,
            page_size=page_size,
            active=active,
        )

    async def get_location(
        self, context: SecurityContext, company_id: UUID, location_id: UUID
    ) -> WarehouseLocation:
        await self._authorization.require(context, company_id, INVENTORY_LOCATION_READ)
        item = await self._directory.get_location(company_id, location_id)
        if item is None:
            raise _not_found("Location")
        return item

    async def list_pools(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        active: bool | None = None,
    ) -> InventoryPage[InventoryPool]:
        await self._authorization.require(context, company_id, INVENTORY_POOL_READ)
        _validate_page(page, page_size)
        return await self._directory.list_pools(
            company_id, page=page, page_size=page_size, active=active
        )

    async def get_pool(
        self, context: SecurityContext, company_id: UUID, pool_id: UUID
    ) -> InventoryPool:
        await self._authorization.require(context, company_id, INVENTORY_POOL_READ)
        item = await self._directory.get_pool(company_id, pool_id)
        if item is None:
            raise _not_found("Inventory pool")
        return item

    async def list_lots(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        product_id: UUID | None = None,
        status: InventoryLotStatus | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> InventoryPage[InventoryLot]:
        await self._authorization.require(context, company_id, INVENTORY_LOT_READ)
        _validate_page(page, page_size)
        if status is not None and not isinstance(status, InventoryLotStatus):
            raise ApplicationError(
                code="VALIDATION_ERROR", message="Invalid lot status.", status_code=422
            )
        return await self._directory.list_lots(
            company_id,
            product_id=product_id,
            status=status,
            page=page,
            page_size=page_size,
        )

    async def get_lot(
        self, context: SecurityContext, company_id: UUID, lot_id: UUID
    ) -> InventoryLot:
        await self._authorization.require(context, company_id, INVENTORY_LOT_READ)
        item = await self._directory.get_lot(company_id, lot_id)
        if item is None:
            raise _not_found("Inventory lot")
        return item


def _validate_page(page: int, page_size: int) -> None:
    if type(page) is not int or not 1 <= page <= 100_000:
        raise ApplicationError(code="VALIDATION_ERROR", message="Invalid page.", status_code=422)
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ApplicationError(
            code="VALIDATION_ERROR", message="Invalid page size.", status_code=422
        )


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND", message=f"{resource} not found.", status_code=404
    )


__all__ = ["InventoryDirectory", "InventoryPage", "InventoryQueries"]
