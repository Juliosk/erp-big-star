"""Application-service coverage for M5 physical catalogue commands and queries."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel
from erp.modules.inventory.application.catalogue import InventoryCatalogService
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
    INVENTORY_WAREHOUSE_READ,
    InventoryAuthorization,
)
from erp.modules.inventory.application.queries import (
    InventoryDirectory,
    InventoryPage,
    InventoryQueries,
)
from erp.modules.inventory.domain import (
    InventoryLot,
    InventoryLotStatus,
    InventoryPool,
    InventoryPoolKind,
    Warehouse,
    WarehouseLocation,
)
from erp.platform.errors import ApplicationError


class FakeAuthorization:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, object, bool]] = []

    async def require(
        self, context: SecurityContext, company_id: UUID, permission: object, *, write: bool = False
    ) -> None:
        self.calls.append((company_id, permission, write))


class FakeStore:
    def __init__(self) -> None:
        self.warehouse: Warehouse | None = None
        self.location: WarehouseLocation | None = None
        self.pool: InventoryPool | None = None
        self.lot: InventoryLot | None = None

    async def create_warehouse(self, warehouse: Warehouse, actor_id: UUID) -> Warehouse:
        self.warehouse = warehouse
        return warehouse

    async def create_location(
        self, location: WarehouseLocation, actor_id: UUID
    ) -> WarehouseLocation:
        self.location = location
        return location

    async def create_pool(self, pool: InventoryPool, actor_id: UUID) -> InventoryPool:
        self.pool = pool
        return pool

    async def create_lot(self, lot: InventoryLot, actor_id: UUID) -> InventoryLot:
        self.lot = lot
        return lot


class FakeDirectory:
    def __init__(self, warehouse: Warehouse | None) -> None:
        self.warehouse = warehouse
        self.list_calls: list[tuple[UUID, int, int, bool | None]] = []

    async def list_warehouses(
        self, company_id: UUID, *, page: int, page_size: int, active: bool | None
    ) -> InventoryPage[Warehouse]:
        self.list_calls.append((company_id, page, page_size, active))
        return InventoryPage(
            (self.warehouse,) if self.warehouse is not None else (), page, page_size, False
        )

    async def get_warehouse(self, company_id: UUID, warehouse_id: UUID) -> Warehouse | None:
        return (
            self.warehouse
            if self.warehouse is not None and self.warehouse.id == warehouse_id
            else None
        )

    async def list_locations(
        self,
        company_id: UUID,
        *,
        warehouse_id: UUID | None,
        page: int,
        page_size: int,
        active: bool | None,
    ) -> InventoryPage[WarehouseLocation]:
        return InventoryPage((), page, page_size, False)

    async def get_location(self, company_id: UUID, location_id: UUID) -> WarehouseLocation | None:
        return None

    async def list_pools(
        self, company_id: UUID, *, page: int, page_size: int, active: bool | None
    ) -> InventoryPage[InventoryPool]:
        return InventoryPage((), page, page_size, False)

    async def get_pool(self, company_id: UUID, pool_id: UUID) -> InventoryPool | None:
        return None

    async def list_lots(
        self,
        company_id: UUID,
        *,
        product_id: UUID | None,
        status: InventoryLotStatus | None,
        page: int,
        page_size: int,
    ) -> InventoryPage[InventoryLot]:
        return InventoryPage((), page, page_size, False)

    async def get_lot(self, company_id: UUID, lot_id: UUID) -> InventoryLot | None:
        return None


def _context(user_id: UUID) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(user_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=frozenset(),
        scopes=frozenset(),
    )


def test_catalogue_service_authorizes_and_builds_all_physical_records() -> None:
    async def scenario() -> None:
        company_id, actor_id = uuid4(), uuid4()
        warehouse_id, product_id = uuid4(), uuid4()
        authorization = FakeAuthorization()
        store = FakeStore()
        service = InventoryCatalogService(
            cast(InventoryCatalogStore, store),
            cast(InventoryAuthorization, authorization),
        )
        context = _context(actor_id)

        warehouse = await service.create_warehouse(
            context, CreateWarehouse(company_id, uuid4(), " wh-01 ", " Principal ")
        )
        location = await service.create_location(
            context, CreateLocation(company_id, warehouse_id, " rua-01 ", " Rua 01 ")
        )
        pool = await service.create_pool(
            context,
            CreateInventoryPool(
                company_id, " mkp ", " Marketplace ", InventoryPoolKind.MARKETPLACE
            ),
        )
        lot = await service.create_lot(
            context, CreateInventoryLot(company_id, product_id, " l-01 ")
        )

        assert warehouse.code == "WH-01"
        assert location.code == "RUA-01"
        assert pool.kind is InventoryPoolKind.MARKETPLACE
        assert lot.status is InventoryLotStatus.OPEN
        assert store.warehouse == warehouse
        assert store.location == location
        assert store.pool == pool
        assert store.lot == lot
        assert authorization.calls == [
            (company_id, INVENTORY_WAREHOUSE_CREATE, True),
            (company_id, INVENTORY_LOCATION_CREATE, True),
            (company_id, INVENTORY_POOL_CREATE, True),
            (company_id, INVENTORY_LOT_CREATE, True),
        ]

    asyncio.run(scenario())


def test_catalogue_service_translates_domain_validation_to_error_contract() -> None:
    async def scenario() -> None:
        service = InventoryCatalogService(
            cast(InventoryCatalogStore, FakeStore()),
            cast(InventoryAuthorization, FakeAuthorization()),
        )
        with pytest.raises(ApplicationError) as captured:
            await service.create_pool(
                _context(uuid4()),
                CreateInventoryPool(uuid4(), "x", "Invalid", InventoryPoolKind.STORE),
            )
        assert captured.value.code == "BUSINESS_VALIDATION_ERROR"
        assert captured.value.status_code == 422

    asyncio.run(scenario())


def test_inventory_queries_authorize_paginate_and_translate_not_found() -> None:
    async def scenario() -> None:
        company_id = uuid4()
        warehouse = Warehouse.create(
            company_id=company_id, branch_id=uuid4(), code="WH-01", name="Principal"
        )
        authorization = FakeAuthorization()
        directory = FakeDirectory(warehouse)
        service = InventoryQueries(
            cast(InventoryDirectory, directory), cast(InventoryAuthorization, authorization)
        )

        page = await service.list_warehouses(
            _context(uuid4()), company_id, page=2, page_size=10, active=True
        )
        found = await service.get_warehouse(_context(uuid4()), company_id, warehouse.id)

        assert page.items == (warehouse,)
        assert found == warehouse
        assert directory.list_calls == [(company_id, 2, 10, True)]
        assert authorization.calls == [
            (company_id, INVENTORY_WAREHOUSE_READ, False),
            (company_id, INVENTORY_WAREHOUSE_READ, False),
        ]
        with pytest.raises(ApplicationError) as captured:
            await service.get_warehouse(_context(uuid4()), company_id, uuid4())
        assert captured.value.code == "RESOURCE_NOT_FOUND"

    asyncio.run(scenario())


@pytest.mark.parametrize(("page", "page_size"), [(0, 10), (1, 0), (100_001, 10), (1, 101)])
def test_inventory_queries_reject_invalid_pagination(page: int, page_size: int) -> None:
    async def scenario() -> None:
        company_id = uuid4()
        service = InventoryQueries(
            cast(InventoryDirectory, FakeDirectory(None)),
            cast(InventoryAuthorization, FakeAuthorization()),
        )
        with pytest.raises(ApplicationError) as captured:
            await service.list_warehouses(
                _context(uuid4()), company_id, page=page, page_size=page_size
            )
        assert captured.value.code == "VALIDATION_ERROR"

    asyncio.run(scenario())


def test_inventory_queries_reject_invalid_lot_status_type_after_authorization() -> None:
    async def scenario() -> None:
        company_id = uuid4()
        service = InventoryQueries(
            cast(InventoryDirectory, FakeDirectory(None)),
            cast(InventoryAuthorization, FakeAuthorization()),
        )
        with pytest.raises(ApplicationError) as captured:
            await service.list_lots(
                _context(uuid4()),
                company_id,
                status=cast(InventoryLotStatus, "INVALID"),
            )
        assert captured.value.code == "VALIDATION_ERROR"

    asyncio.run(scenario())
