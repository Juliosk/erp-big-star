"""Pure M4 order-to-reservation snapshot rules."""

from uuid import uuid4

import pytest

from erp.modules.sales.domain import (
    SalesOrder,
    SalesOrderReservation,
    SalesOrderReservationStatus,
)


def _order() -> SalesOrder:
    return SalesOrder.create_from_quote(
        company_id=uuid4(),
        number="SO-RES-1",
        source_quote_id=uuid4(),
        source_quote_revision_number=1,
        customer_id=uuid4(),
        seller_id=uuid4(),
        currency="BRL",
        lines=((uuid4(), uuid4(), "2.250000", "30.00", "0", uuid4()),),
    )


def test_reservation_snapshot_requires_approved_order_and_freezes_lines() -> None:
    draft = _order()
    with pytest.raises(ValueError, match="only approved"):
        SalesOrderReservation.request(draft)

    approved = draft.approve()
    reservation = SalesOrderReservation.request(approved)

    assert reservation.company_id == approved.company_id
    assert reservation.order_id == approved.id
    assert reservation.order_version == approved.version
    assert reservation.status is SalesOrderReservationStatus.REQUESTED
    assert reservation.lines[0].order_item_id == approved.items[0].id
    assert reservation.lines[0].quantity == approved.items[0].quantity
    assert reservation.lines[0].pricing_snapshot_id == approved.items[0].pricing_snapshot_id


def test_reservation_lifecycle_is_strict_and_versioned() -> None:
    requested = SalesOrderReservation.request(_order().approve())
    inventory_reservation_id = uuid4()
    held = requested.hold(inventory_reservation_id)
    assert held.inventory_reservation_id == inventory_reservation_id
    assert held.status is SalesOrderReservationStatus.HELD
    assert held.version == 2
    assert held.release().status is SalesOrderReservationStatus.RELEASED
    assert held.cancel().status is SalesOrderReservationStatus.CANCELLED
    assert requested.cancel().status is SalesOrderReservationStatus.CANCELLED
    with pytest.raises(ValueError, match="only requested"):
        held.hold(uuid4())
    with pytest.raises(ValueError, match="only held"):
        requested.release()
