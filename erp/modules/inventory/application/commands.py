"""Technology-neutral creation commands and persistence ports for M5."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from erp.modules.inventory.domain import (
    InventoryLot,
    InventoryPool,
    InventoryPoolKind,
    Warehouse,
    WarehouseLocation,
)


@dataclass(frozen=True, slots=True)
class CreateWarehouse:
    company_id: UUID
    branch_id: UUID
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class CreateLocation:
    company_id: UUID
    warehouse_id: UUID
    code: str
    name: str
    parent_location_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CreateInventoryPool:
    company_id: UUID
    code: str
    name: str
    kind: InventoryPoolKind


@dataclass(frozen=True, slots=True)
class CreateInventoryLot:
    company_id: UUID
    product_id: UUID
    code: str
    expires_on: date | None = None


class InventoryCatalogStore(Protocol):
    async def create_warehouse(self, warehouse: Warehouse, actor_id: UUID) -> Warehouse: ...

    async def create_location(
        self, location: WarehouseLocation, actor_id: UUID
    ) -> WarehouseLocation: ...

    async def create_pool(self, pool: InventoryPool, actor_id: UUID) -> InventoryPool: ...

    async def create_lot(self, lot: InventoryLot, actor_id: UUID) -> InventoryLot: ...


__all__ = [
    "CreateInventoryLot",
    "CreateInventoryPool",
    "CreateLocation",
    "CreateWarehouse",
    "InventoryCatalogStore",
]
