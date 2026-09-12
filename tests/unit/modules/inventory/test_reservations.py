"""Pure inventory reservation rules: HARD/SOFT, expiry and ATP math."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.inventory.domain import (
    InventoryAvailability,
    InventoryReservation,
    InventoryReservationAllocation,
    InventoryReservationKind,
    InventoryReservationStatus,
    InventoryState,
    Quantity,
)


def allocation(*, quantity: str = "3") -> InventoryReservationAllocation:
    return InventoryReservationAllocation.create(
        reservation_id=uuid4(),
        company_id=uuid4(),
        product_id=uuid4(),
        warehouse_id=uuid4(),
        quantity=Quantity.of(quantity),
    )


def reservation(
    *,
    kind: InventoryReservationKind = InventoryReservationKind.HARD,
    expires_at: datetime | None = None,
) -> InventoryReservation:
    created_at = datetime(2026, 9, 12, 12, tzinfo=UTC)
    return InventoryReservation.create(
        company_id=uuid4(),
        reservation_kind=kind,
        reference_type="order",
        reference_id=uuid4(),
        created_by=uuid4(),
        allocations=(allocation(),),
        created_at=created_at,
        expires_at=expires_at,
    )


def test_reservation_normalizes_reference_and_rebinds_allocations() -> None:
    item = reservation()

    assert item.reference_type == "ORDER"
    assert item.status is InventoryReservationStatus.ACTIVE
    assert item.version == 1
    assert item.allocations[0].reservation_id == item.id
    assert item.allocations[0].company_id == item.company_id
    with pytest.raises(FrozenInstanceError):
        item.status = InventoryReservationStatus.RELEASED  # type: ignore[misc]


@pytest.mark.parametrize("kind", list(InventoryReservationKind))
def test_reservation_accepts_official_hard_soft_kinds(kind: InventoryReservationKind) -> None:
    assert reservation(kind=kind).reservation_kind is kind


def test_reservation_release_and_expire_are_terminal_transitions() -> None:
    created_at = datetime(2026, 9, 12, 12, tzinfo=UTC)
    item = reservation(expires_at=created_at + timedelta(hours=1))

    released = item.release()
    expired = item.expire(created_at + timedelta(hours=2))

    assert released.status is InventoryReservationStatus.RELEASED
    assert released.version == 2
    assert released.release() is released
    assert expired.status is InventoryReservationStatus.EXPIRED
    assert expired.version == 2
    assert expired.expire(created_at + timedelta(hours=3)) is expired
    with pytest.raises(ValueError, match="active"):
        released.expire(created_at + timedelta(hours=2))
    with pytest.raises(ValueError, match="active"):
        expired.release()


def test_expiration_cannot_happen_before_deadline() -> None:
    created_at = datetime(2026, 9, 12, 12, tzinfo=UTC)
    item = reservation(expires_at=created_at + timedelta(hours=1))

    with pytest.raises(ValueError, match="expires_at"):
        item.expire(created_at + timedelta(minutes=59))


def test_hard_reservation_counts_only_same_active_stock_bucket() -> None:
    item = reservation()
    bucket = item.allocations[0]
    other_bucket = InventoryReservationAllocation.create(
        reservation_id=item.id,
        company_id=item.company_id,
        product_id=uuid4(),
        warehouse_id=bucket.warehouse_id,
        quantity=Quantity.of("3"),
    )

    assert item.hard_quantity_for(bucket) == Decimal("3")
    assert item.hard_quantity_for(other_bucket) == Decimal("0")
    assert item.release().hard_quantity_for(bucket) == Decimal("0")
    assert reservation(kind=InventoryReservationKind.SOFT).hard_quantity_for(bucket) == Decimal("0")


def test_availability_subtracts_hard_and_tracks_soft_separately() -> None:
    availability = InventoryAvailability.calculate(
        company_id=uuid4(),
        product_id=uuid4(),
        warehouse_id=uuid4(),
        location_id=None,
        lot_id=None,
        pool_id=None,
        state=InventoryState.AVAILABLE,
        on_hand=Quantity.of("10"),
        hard_reserved=Quantity.of("4"),
        soft_reserved=Quantity.of("9"),
        version=3,
    )

    assert availability.available.value == Decimal("6")
    assert availability.soft_reserved.value == Decimal("9")
    assert availability.version == 3


@pytest.mark.parametrize("value", ["0", "-1", "1.1234567"])
def test_reservation_allocation_requires_positive_six_decimal_quantity(value: str) -> None:
    with pytest.raises(ValueError, match="quantity"):
        allocation(quantity=value)


def test_reservation_requires_aware_expiry_after_creation() -> None:
    created_at = datetime(2026, 9, 12, 12, tzinfo=UTC)
    with pytest.raises(ValueError, match="expires_at"):
        InventoryReservation.create(
            company_id=uuid4(),
            reservation_kind=InventoryReservationKind.HARD,
            reference_type="order",
            reference_id=uuid4(),
            created_by=uuid4(),
            allocations=(allocation(),),
            created_at=created_at,
            expires_at=created_at,
        )
    with pytest.raises(ValueError, match="timezone"):
        InventoryReservation.create(
            company_id=uuid4(),
            reservation_kind=InventoryReservationKind.HARD,
            reference_type="order",
            reference_id=uuid4(),
            created_by=uuid4(),
            allocations=(allocation(),),
            created_at=datetime.fromisoformat("2026-09-12T12:00:00"),
        )
