"""Explicit M5 integration surface; no persistence types are exported."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
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
class OrderReservationLineContract:
    product_id: UUID
    quantity: Decimal
    warehouse_id: UUID
    location_id: UUID | None = None
    lot_id: UUID | None = None
    pool_id: UUID | None = None
    state: str = "AVAILABLE"


@dataclass(frozen=True, slots=True)
class ReserveOrderInventoryContract:
    company_id: UUID
    order_id: UUID
    lines: tuple[OrderReservationLineContract, ...]
    idempotency_key: str
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None
    reservation_kind: InventoryReservationKindContract = InventoryReservationKindContract.HARD
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ExtendOrderInventoryHoldContract:
    company_id: UUID
    reservation_id: UUID
    expires_at: datetime
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None


@dataclass(frozen=True, slots=True)
class ReleaseOrderInventoryContract:
    company_id: UUID
    reservation_id: UUID
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None


class OrderInventoryReservationGateway(Protocol):
    """M5-owned anti-corruption boundary consumed by the M4 composition adapter."""

    async def reserve_order(
        self, command: ReserveOrderInventoryContract, actor_id: UUID
    ) -> OrderInventoryReservationResultContract: ...

    async def extend_order_hold(
        self, command: ExtendOrderInventoryHoldContract, actor_id: UUID
    ) -> OrderInventoryReservationResultContract: ...

    async def get_order_reservation(
        self, company_id: UUID, reservation_id: UUID
    ) -> InventoryReservationReference | None: ...

    async def release_order(
        self, command: ReleaseOrderInventoryContract, actor_id: UUID
    ) -> OrderInventoryReservationResultContract: ...


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
class OrderInventoryReservationResultContract:
    reservation: InventoryReservationReference
    event_id: UUID
    audit_event_id: UUID


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
    "ExtendOrderInventoryHoldContract",
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
    "OrderInventoryReservationGateway",
    "OrderInventoryReservationResultContract",
    "OrderReservationLineContract",
    "ReleaseOrderInventoryContract",
    "ReserveOrderInventoryContract",
]
