"""Explicit M5 integration surface; no persistence types are exported."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from erp.modules.inventory.application.permissions import (
    INVENTORY_AVAILABILITY_READ,
    INVENTORY_BALANCE_READ,
    INVENTORY_RESERVATION_MANAGE,
    InventoryAuthorization,
)


class InventoryReservationKindContract(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


class InventoryReservationStatusContract(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


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


@dataclass(frozen=True, slots=True)
class InventoryAvailabilityReference:
    company_id: UUID
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    state: str
    on_hand: Decimal
    hard_reserved: Decimal
    soft_reserved: Decimal
    available: Decimal
    version: int


@dataclass(frozen=True, slots=True)
class InventoryReservationAllocationReference:
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    state: str
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class InventoryReservationReference:
    id: UUID
    company_id: UUID
    reservation_kind: InventoryReservationKindContract
    status: InventoryReservationStatusContract
    reference_type: str
    reference_id: UUID
    expires_at: datetime | None
    version: int
    allocations: tuple[InventoryReservationAllocationReference, ...]


@dataclass(frozen=True, slots=True)
class InventoryReservationCreated:
    event_id: UUID
    company_id: UUID
    reservation_id: UUID
    reservation_kind: InventoryReservationKindContract
    reference_type: str
    reference_id: UUID
    allocation_count: int


@dataclass(frozen=True, slots=True)
class InventoryReservationReleased:
    event_id: UUID
    company_id: UUID
    reservation_id: UUID
    reference_type: str
    reference_id: UUID


@dataclass(frozen=True, slots=True)
class InventoryReservationExpired:
    event_id: UUID
    company_id: UUID
    reservation_id: UUID
    reference_type: str
    reference_id: UUID


__all__ = [
    "INVENTORY_AVAILABILITY_READ",
    "INVENTORY_BALANCE_READ",
    "INVENTORY_RESERVATION_MANAGE",
    "InventoryAuthorization",
    "InventoryAvailabilityReference",
    "InventoryBalanceReference",
    "InventoryReservationAllocationReference",
    "InventoryReservationCreated",
    "InventoryReservationExpired",
    "InventoryReservationKindContract",
    "InventoryReservationReference",
    "InventoryReservationReleased",
    "InventoryReservationStatusContract",
]
