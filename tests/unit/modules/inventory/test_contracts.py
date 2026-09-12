"""M5 public contracts export references without infrastructure coupling."""

from decimal import Decimal
from uuid import uuid4

from erp.modules.inventory.application.permissions import (
    INVENTORY_BALANCE_READ,
    INVENTORY_RESERVATION_MANAGE,
)
from erp.modules.inventory.contracts import (
    InventoryAvailabilityReference,
    InventoryBalanceReference,
    InventoryReservationAllocationReference,
    InventoryReservationCreated,
    InventoryReservationKindContract,
    InventoryReservationReference,
    InventoryReservationStatusContract,
)


def test_public_contract_exports_balance_reference_and_read_permission() -> None:
    reference = InventoryBalanceReference(
        company_id=uuid4(),
        product_id=uuid4(),
        warehouse_id=uuid4(),
        location_id=None,
        lot_id=None,
        pool_id=uuid4(),
        state="AVAILABLE",
        on_hand=Decimal("12"),
        reserved=Decimal("2"),
        available=Decimal("10"),
        version=1,
    )

    assert str(INVENTORY_BALANCE_READ) == "inventory.balance.read"
    assert reference.available == Decimal("10")


def test_public_contract_exports_reservation_and_availability_references() -> None:
    company_id, product_id, warehouse_id = uuid4(), uuid4(), uuid4()
    allocation = InventoryReservationAllocationReference(
        product_id=product_id,
        warehouse_id=warehouse_id,
        location_id=None,
        lot_id=None,
        pool_id=None,
        state="AVAILABLE",
        quantity=Decimal("2"),
    )
    reservation = InventoryReservationReference(
        id=uuid4(),
        company_id=company_id,
        reservation_kind=InventoryReservationKindContract.HARD,
        status=InventoryReservationStatusContract.ACTIVE,
        reference_type="ORDER",
        reference_id=uuid4(),
        expires_at=None,
        version=1,
        allocations=(allocation,),
    )
    availability = InventoryAvailabilityReference(
        company_id=company_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        location_id=None,
        lot_id=None,
        pool_id=None,
        state="AVAILABLE",
        on_hand=Decimal("5"),
        hard_reserved=Decimal("2"),
        soft_reserved=Decimal("1"),
        available=Decimal("3"),
        version=4,
    )
    event = InventoryReservationCreated(
        event_id=uuid4(),
        company_id=company_id,
        reservation_id=reservation.id,
        reservation_kind=InventoryReservationKindContract.HARD,
        reference_type=reservation.reference_type,
        reference_id=reservation.reference_id,
        allocation_count=1,
    )

    assert str(INVENTORY_RESERVATION_MANAGE) == "inventory.reservation.manage"
    assert reservation.allocations == (allocation,)
    assert availability.available == Decimal("3")
    assert event.allocation_count == 1
