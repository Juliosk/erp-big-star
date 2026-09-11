"""Technology-neutral creation commands and persistence ports for M5."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from erp.modules.inventory.domain import (
    InventoryBalance,
    InventoryLot,
    InventoryPool,
    InventoryPoolKind,
    InventoryState,
    Quantity,
    Warehouse,
    WarehouseLocation,
)


class InventoryAdjustmentType(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    BALANCE = "BALANCE"


@dataclass(frozen=True, slots=True)
class CommandMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None


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


@dataclass(frozen=True, slots=True)
class InventoryAdjustmentLine:
    product_id: UUID
    warehouse_id: UUID
    quantity: Decimal
    location_id: UUID | None = None
    lot_id: UUID | None = None
    pool_id: UUID | None = None
    state: str = "AVAILABLE"

    def payload(self) -> dict[str, object]:
        return {
            "product_id": str(self.product_id),
            "warehouse_id": str(self.warehouse_id),
            "location_id": str(self.location_id) if self.location_id is not None else None,
            "lot_id": str(self.lot_id) if self.lot_id is not None else None,
            "pool_id": str(self.pool_id) if self.pool_id is not None else None,
            "state": self.state,
            "quantity": str(self.quantity),
        }


@dataclass(frozen=True, slots=True)
class CreateInventoryAdjustment:
    company_id: UUID
    adjustment_type: InventoryAdjustmentType
    reason: str
    lines: tuple[InventoryAdjustmentLine, ...]
    idempotency_key: str
    metadata: CommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "adjustment_type": self.adjustment_type,
            "reason": self.reason,
            "lines": [line.payload() for line in self.lines],
        }


@dataclass(frozen=True, slots=True)
class InventoryAdjustmentResult:
    transaction_id: UUID
    balances: tuple[InventoryBalance, ...]
    event_id: UUID | None
    audit_event_id: UUID | None
    idempotency_replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "transaction_id": str(self.transaction_id),
            "balances": [
                {
                    "id": str(balance.id),
                    "company_id": str(balance.company_id),
                    "product_id": str(balance.product_id),
                    "warehouse_id": str(balance.warehouse_id),
                    "location_id": str(balance.location_id)
                    if balance.location_id is not None
                    else None,
                    "lot_id": str(balance.lot_id) if balance.lot_id is not None else None,
                    "pool_id": str(balance.pool_id) if balance.pool_id is not None else None,
                    "state": balance.state,
                    "quantity": f"{balance.quantity.value:.6f}",
                    "version": balance.version,
                }
                for balance in self.balances
            ],
            "event_id": str(self.event_id) if self.event_id is not None else None,
            "audit_event_id": str(self.audit_event_id) if self.audit_event_id is not None else None,
            "idempotency_replayed": self.idempotency_replayed,
        }

    @classmethod
    def replay(cls, body: dict[str, object]) -> InventoryAdjustmentResult:
        balances = body.get("balances")
        if not isinstance(balances, list):
            balances = []
        return cls(
            transaction_id=UUID(str(body["transaction_id"])),
            balances=tuple(
                InventoryBalance(
                    id=UUID(str(item["id"])),
                    company_id=UUID(str(item["company_id"])),
                    product_id=UUID(str(item["product_id"])),
                    warehouse_id=UUID(str(item["warehouse_id"])),
                    location_id=UUID(str(item["location_id"]))
                    if item["location_id"] is not None
                    else None,
                    lot_id=UUID(str(item["lot_id"])) if item["lot_id"] is not None else None,
                    pool_id=UUID(str(item["pool_id"])) if item["pool_id"] is not None else None,
                    state=InventoryState(str(item["state"])),
                    quantity=Quantity.of(str(item["quantity"])),
                    version=int(str(item["version"])),
                )
                for item in balances
                if isinstance(item, dict)
            ),
            event_id=UUID(str(body["event_id"])) if body["event_id"] is not None else None,
            audit_event_id=UUID(str(body["audit_event_id"]))
            if body["audit_event_id"] is not None
            else None,
            idempotency_replayed=True,
        )


class InventoryCatalogStore(Protocol):
    async def create_warehouse(self, warehouse: Warehouse, actor_id: UUID) -> Warehouse: ...

    async def create_location(
        self, location: WarehouseLocation, actor_id: UUID
    ) -> WarehouseLocation: ...

    async def create_pool(self, pool: InventoryPool, actor_id: UUID) -> InventoryPool: ...

    async def create_lot(self, lot: InventoryLot, actor_id: UUID) -> InventoryLot: ...


__all__ = [
    "CommandMetadata",
    "CreateInventoryAdjustment",
    "CreateInventoryLot",
    "CreateInventoryPool",
    "CreateLocation",
    "CreateWarehouse",
    "InventoryAdjustmentLine",
    "InventoryAdjustmentResult",
    "InventoryAdjustmentType",
    "InventoryCatalogStore",
]
