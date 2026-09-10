"""Authorized creation services for the M5 physical catalogue."""

from collections.abc import Callable
from typing import TypeVar

from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.application.commands import (
    CreateInventoryLot,
    CreateInventoryPool,
    CreateLocation,
    CreateWarehouse,
    InventoryCatalogStore,
)
from erp.modules.inventory.application.permissions import (
    INVENTORY_LOCATION_CREATE,
    INVENTORY_LOT_CREATE,
    INVENTORY_POOL_CREATE,
    INVENTORY_WAREHOUSE_CREATE,
    InventoryAuthorization,
)
from erp.modules.inventory.domain import InventoryLot, InventoryPool, Warehouse, WarehouseLocation
from erp.platform.errors import ApplicationError, ErrorDetail

T = TypeVar("T")


class InventoryCatalogService:
    """Build validated aggregates and persist them after RBAC + company checks."""

    def __init__(self, store: InventoryCatalogStore, authorization: InventoryAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create_warehouse(
        self, context: SecurityContext, command: CreateWarehouse
    ) -> Warehouse:
        await self._authorization.require(
            context, command.company_id, INVENTORY_WAREHOUSE_CREATE, write=True
        )
        warehouse = self._build(
            lambda: Warehouse.create(
                company_id=command.company_id,
                branch_id=command.branch_id,
                code=command.code,
                name=command.name,
            )
        )
        return await self._store.create_warehouse(warehouse, context.principal.user_id)

    async def create_location(
        self, context: SecurityContext, command: CreateLocation
    ) -> WarehouseLocation:
        await self._authorization.require(
            context, command.company_id, INVENTORY_LOCATION_CREATE, write=True
        )
        location = self._build(
            lambda: WarehouseLocation.create(
                company_id=command.company_id,
                warehouse_id=command.warehouse_id,
                code=command.code,
                name=command.name,
                parent_location_id=command.parent_location_id,
            )
        )
        return await self._store.create_location(location, context.principal.user_id)

    async def create_pool(
        self, context: SecurityContext, command: CreateInventoryPool
    ) -> InventoryPool:
        await self._authorization.require(
            context, command.company_id, INVENTORY_POOL_CREATE, write=True
        )
        pool = self._build(
            lambda: InventoryPool.create(
                company_id=command.company_id,
                code=command.code,
                name=command.name,
                kind=command.kind,
            )
        )
        return await self._store.create_pool(pool, context.principal.user_id)

    async def create_lot(
        self, context: SecurityContext, command: CreateInventoryLot
    ) -> InventoryLot:
        await self._authorization.require(
            context, command.company_id, INVENTORY_LOT_CREATE, write=True
        )
        lot = self._build(
            lambda: InventoryLot.create(
                company_id=command.company_id,
                product_id=command.product_id,
                code=command.code,
                expires_on=command.expires_on,
            )
        )
        return await self._store.create_lot(lot, context.principal.user_id)

    @staticmethod
    def _build(factory: Callable[[], T]) -> T:
        try:
            return factory()
        except ValueError as error:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid inventory data.",
                status_code=422,
                details=[ErrorDetail(message=str(error))],
            ) from error


# Name used by composition roots that model all four commands as one service.
InventoryCreationService = InventoryCatalogService


__all__ = ["InventoryCatalogService", "InventoryCreationService"]
