"""Inventory reservation domain rules for HARD/SOFT ATP control."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.inventory.domain.stock import InventoryState, Quantity


class InventoryReservationKind(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


class InventoryReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


def _aware(value: datetime | None, *, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a datetime.")
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware.")
    return value


def _required_aware(value: datetime, *, field: str) -> datetime:
    candidate = _aware(value, field=field)
    if candidate is None:
        raise ValueError(f"{field} is required.")
    return candidate


def _reference_type(value: str) -> str:
    candidate = value.strip().upper()
    if not 2 <= len(candidate) <= 64 or not candidate.replace("_", "").isalnum():
        raise ValueError("reference_type must contain 2 to 64 canonical characters.")
    return candidate


@dataclass(frozen=True, slots=True)
class InventoryReservationAllocation:
    id: UUID
    reservation_id: UUID
    company_id: UUID
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    state: InventoryState
    quantity: Quantity

    def __post_init__(self) -> None:
        required = (
            self.id,
            self.reservation_id,
            self.company_id,
            self.product_id,
            self.warehouse_id,
        )
        if not all(isinstance(value, UUID) for value in required):
            raise ValueError(
                "Allocation identity, reservation, company, product and warehouse must be UUIDs."
            )
        for optional in (self.location_id, self.lot_id, self.pool_id):
            if optional is not None and not isinstance(optional, UUID):
                raise ValueError("Optional allocation dimensions must be UUIDs when present.")
        if not isinstance(self.state, InventoryState):
            raise ValueError("state must be an official inventory state.")
        if not isinstance(self.quantity, Quantity):
            raise ValueError("quantity must be an inventory Quantity.")
        if self.quantity.value <= Decimal("0"):
            raise ValueError("reservation allocation quantity must be positive.")

    @classmethod
    def create(
        cls,
        *,
        reservation_id: UUID,
        company_id: UUID,
        product_id: UUID,
        warehouse_id: UUID,
        quantity: Quantity,
        state: InventoryState = InventoryState.AVAILABLE,
        location_id: UUID | None = None,
        lot_id: UUID | None = None,
        pool_id: UUID | None = None,
    ) -> InventoryReservationAllocation:
        return cls(
            id=uuid4(),
            reservation_id=reservation_id,
            company_id=company_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            location_id=location_id,
            lot_id=lot_id,
            pool_id=pool_id,
            state=state,
            quantity=quantity,
        )

    def same_stock_bucket(self, other: InventoryReservationAllocation) -> bool:
        return (
            self.company_id,
            self.product_id,
            self.warehouse_id,
            self.location_id,
            self.lot_id,
            self.pool_id,
            self.state,
        ) == (
            other.company_id,
            other.product_id,
            other.warehouse_id,
            other.location_id,
            other.lot_id,
            other.pool_id,
            other.state,
        )


@dataclass(frozen=True, slots=True)
class InventoryReservation:
    id: UUID
    company_id: UUID
    reservation_kind: InventoryReservationKind
    status: InventoryReservationStatus
    reference_type: str
    reference_id: UUID
    expires_at: datetime | None
    created_at: datetime
    created_by: UUID
    version: int
    allocations: tuple[InventoryReservationAllocation, ...]

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (self.id, self.company_id, self.reference_id, self.created_by)
        ):
            raise ValueError("Reservation identity, company, reference and actor must be UUIDs.")
        if not isinstance(self.reservation_kind, InventoryReservationKind):
            raise ValueError("reservation_kind must be HARD or SOFT.")
        if not isinstance(self.status, InventoryReservationStatus):
            raise ValueError("status must be an official reservation status.")
        object.__setattr__(self, "reference_type", _reference_type(self.reference_type))
        object.__setattr__(self, "created_at", _aware(self.created_at, field="created_at"))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, field="expires_at"))
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at.")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer.")
        if not self.allocations:
            raise ValueError("reservation must contain at least one allocation.")
        for allocation in self.allocations:
            if allocation.reservation_id != self.id or allocation.company_id != self.company_id:
                raise ValueError("allocation must belong to the reservation company.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        reservation_kind: InventoryReservationKind,
        reference_type: str,
        reference_id: UUID,
        created_by: UUID,
        allocations: tuple[InventoryReservationAllocation, ...],
        expires_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> InventoryReservation:
        now = _required_aware(created_at or datetime.now(UTC), field="created_at")
        reservation_id = uuid4()
        normalized_allocations = tuple(
            replace(allocation, reservation_id=reservation_id, company_id=company_id)
            for allocation in allocations
        )
        return cls(
            id=reservation_id,
            company_id=company_id,
            reservation_kind=reservation_kind,
            status=InventoryReservationStatus.ACTIVE,
            reference_type=reference_type,
            reference_id=reference_id,
            expires_at=expires_at,
            created_at=now,
            created_by=created_by,
            version=1,
            allocations=normalized_allocations,
        )

    def release(self) -> InventoryReservation:
        if self.status is InventoryReservationStatus.RELEASED:
            return self
        if self.status is not InventoryReservationStatus.ACTIVE:
            raise ValueError("only active reservations can be released.")
        return replace(self, status=InventoryReservationStatus.RELEASED, version=self.version + 1)

    def expire(self, now: datetime | None = None) -> InventoryReservation:
        if self.status is InventoryReservationStatus.EXPIRED:
            return self
        if self.status is not InventoryReservationStatus.ACTIVE:
            raise ValueError("only active reservations can expire.")
        candidate = _required_aware(now or datetime.now(UTC), field="now")
        if self.expires_at is not None and candidate < self.expires_at:
            raise ValueError("reservation has not reached expires_at.")
        return replace(self, status=InventoryReservationStatus.EXPIRED, version=self.version + 1)

    def hard_quantity_for(self, bucket: InventoryReservationAllocation) -> Decimal:
        if (
            self.status is not InventoryReservationStatus.ACTIVE
            or self.reservation_kind is not InventoryReservationKind.HARD
        ):
            return Decimal("0")
        return sum(
            (
                allocation.quantity.value
                for allocation in self.allocations
                if allocation.same_stock_bucket(bucket)
            ),
            Decimal("0"),
        )


@dataclass(frozen=True, slots=True)
class InventoryAvailability:
    company_id: UUID
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    state: InventoryState
    on_hand: Quantity
    hard_reserved: Quantity
    soft_reserved: Quantity
    available: Quantity
    version: int

    def __post_init__(self) -> None:
        if self.available.value != self.on_hand.value - self.hard_reserved.value:
            raise ValueError("available quantity must equal on_hand minus HARD reservations.")
        if self.available.value < Decimal("0"):
            raise ValueError("available quantity cannot be negative.")

    @classmethod
    def calculate(
        cls,
        *,
        company_id: UUID,
        product_id: UUID,
        warehouse_id: UUID,
        state: InventoryState,
        on_hand: Quantity,
        hard_reserved: Quantity,
        soft_reserved: Quantity,
        version: int,
        location_id: UUID | None = None,
        lot_id: UUID | None = None,
        pool_id: UUID | None = None,
    ) -> InventoryAvailability:
        return cls(
            company_id=company_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            location_id=location_id,
            lot_id=lot_id,
            pool_id=pool_id,
            state=state,
            on_hand=on_hand,
            hard_reserved=hard_reserved,
            soft_reserved=soft_reserved,
            available=Quantity(on_hand.value - hard_reserved.value),
            version=version,
        )


__all__ = [
    "InventoryAvailability",
    "InventoryReservation",
    "InventoryReservationAllocation",
    "InventoryReservationKind",
    "InventoryReservationStatus",
]
