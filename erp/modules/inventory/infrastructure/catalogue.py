"""PostgreSQL adapters for M5 catalogue reads and writes."""

from uuid import UUID

from erp.modules.inventory.application.commands import InventoryCatalogStore
from erp.modules.inventory.application.queries import InventoryDirectory, InventoryPage
from erp.modules.inventory.domain import (
    InventoryLot,
    InventoryLotStatus,
    InventoryPool,
    Warehouse,
    WarehouseLocation,
)
from erp.modules.inventory.infrastructure.repository import (
    InventoryLotRepository,
    InventoryPoolRepository,
    WarehouseLocationRepository,
    WarehouseRepository,
)
from erp.platform.database import Database


class PostgresInventoryCatalogue(InventoryCatalogStore, InventoryDirectory):
    """Session-owning adapter; every repository is constructed with company scope."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_warehouse(self, warehouse: Warehouse, actor_id: UUID) -> Warehouse:
        async with self._database.session() as session, session.begin():
            await WarehouseRepository(session, company_id=warehouse.company_id).add(
                warehouse, actor_id=actor_id
            )
        return warehouse

    async def create_location(
        self, location: WarehouseLocation, actor_id: UUID
    ) -> WarehouseLocation:
        async with self._database.session() as session, session.begin():
            await WarehouseLocationRepository(session, company_id=location.company_id).add(
                location, actor_id=actor_id
            )
        return location

    async def create_pool(self, pool: InventoryPool, actor_id: UUID) -> InventoryPool:
        async with self._database.session() as session, session.begin():
            await InventoryPoolRepository(session, company_id=pool.company_id).add(
                pool, actor_id=actor_id
            )
        return pool

    async def create_lot(self, lot: InventoryLot, actor_id: UUID) -> InventoryLot:
        async with self._database.session() as session, session.begin():
            await InventoryLotRepository(session, company_id=lot.company_id).add(
                lot, actor_id=actor_id
            )
        return lot

    async def list_warehouses(
        self, company_id: UUID, *, page: int, page_size: int, active: bool | None
    ) -> InventoryPage[Warehouse]:
        async with self._database.session() as session:
            repository = WarehouseRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list(limit=page_size, offset=offset, active=active)
            more = await repository.list(limit=1, offset=offset + page_size, active=active)
            return InventoryPage(items, page, page_size, bool(more))

    async def get_warehouse(self, company_id: UUID, warehouse_id: UUID) -> Warehouse | None:
        async with self._database.session() as session:
            return await WarehouseRepository(session, company_id=company_id).get(warehouse_id)

    async def list_locations(
        self,
        company_id: UUID,
        *,
        warehouse_id: UUID | None,
        page: int,
        page_size: int,
        active: bool | None,
    ) -> InventoryPage[WarehouseLocation]:
        async with self._database.session() as session:
            repository = WarehouseLocationRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list(
                warehouse_id=warehouse_id,
                limit=page_size,
                offset=offset,
                active=active,
            )
            more = await repository.list(
                warehouse_id=warehouse_id,
                limit=1,
                offset=offset + page_size,
                active=active,
            )
            return InventoryPage(items, page, page_size, bool(more))

    async def get_location(self, company_id: UUID, location_id: UUID) -> WarehouseLocation | None:
        async with self._database.session() as session:
            return await WarehouseLocationRepository(session, company_id=company_id).get(
                location_id
            )

    async def list_pools(
        self, company_id: UUID, *, page: int, page_size: int, active: bool | None
    ) -> InventoryPage[InventoryPool]:
        async with self._database.session() as session:
            repository = InventoryPoolRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list(limit=page_size, offset=offset, active=active)
            more = await repository.list(limit=1, offset=offset + page_size, active=active)
            return InventoryPage(items, page, page_size, bool(more))

    async def get_pool(self, company_id: UUID, pool_id: UUID) -> InventoryPool | None:
        async with self._database.session() as session:
            return await InventoryPoolRepository(session, company_id=company_id).get(pool_id)

    async def list_lots(
        self,
        company_id: UUID,
        *,
        product_id: UUID | None,
        status: InventoryLotStatus | None,
        page: int,
        page_size: int,
    ) -> InventoryPage[InventoryLot]:
        async with self._database.session() as session:
            repository = InventoryLotRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list(
                product_id=product_id,
                status=status,
                limit=page_size,
                offset=offset,
            )
            more = await repository.list(
                product_id=product_id,
                status=status,
                limit=1,
                offset=offset + page_size,
            )
            return InventoryPage(items, page, page_size, bool(more))

    async def get_lot(self, company_id: UUID, lot_id: UUID) -> InventoryLot | None:
        async with self._database.session() as session:
            return await InventoryLotRepository(session, company_id=company_id).get(lot_id)


# US spelling is a convenient import for API composition and external callers.
PostgresInventoryCatalog = PostgresInventoryCatalogue
PostgresInventoryDirectory = PostgresInventoryCatalogue


__all__ = [
    "PostgresInventoryCatalog",
    "PostgresInventoryCatalogue",
    "PostgresInventoryDirectory",
]
