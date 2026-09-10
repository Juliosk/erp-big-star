"""Explicit M5 integration surface; no persistence types are exported."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from erp.modules.inventory.application.permissions import (
    INVENTORY_BALANCE_READ,
    InventoryAuthorization,
)


@dataclass(frozen=True, slots=True)
class InventoryBalanceReference:
    company_id: UUID
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID
    state: str
    on_hand: Decimal
    reserved: Decimal
    available: Decimal
    version: int


__all__ = ["INVENTORY_BALANCE_READ", "InventoryAuthorization", "InventoryBalanceReference"]
