"""Pure M4 Sales Order aggregate rules."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from erp.modules.sales.domain import SalesOrder, SalesOrderStatus


def _order() -> SalesOrder:
    return SalesOrder.create_from_quote(
        company_id=uuid4(),
        number="SO-0001",
        source_quote_id=uuid4(),
        source_quote_revision_number=2,
        customer_id=uuid4(),
        seller_id=uuid4(),
        currency="BRL",
        lines=((uuid4(), uuid4(), "2.500000", "20.00", "5.00", uuid4()),),
    )


def test_order_preserves_decimal_precision_and_pricing_snapshot() -> None:
    order = _order()
    assert order.status is SalesOrderStatus.DRAFT
    assert order.items[0].quantity == Decimal("2.500000")
    assert order.gross_amount == Decimal("50.00")
    assert order.discount_amount == Decimal("5.00")
    assert order.net_amount == Decimal("45.00")
    assert order.items[0].pricing_snapshot_id is not None


def test_order_state_machine_is_strict() -> None:
    draft = _order()
    approved = draft.approve()
    assert approved.status is SalesOrderStatus.APPROVED
    assert approved.complete().status is SalesOrderStatus.COMPLETED
    assert approved.cancel().status is SalesOrderStatus.CANCELLED
    with pytest.raises(ValueError, match="only approved"):
        draft.complete()
    with pytest.raises(ValueError, match="only draft"):
        approved.approve()


def test_order_rejects_invalid_lines_and_duplicate_products() -> None:
    product_id = uuid4()
    company_id = uuid4()
    source_quote_id = uuid4()
    customer_id = uuid4()
    seller_id = uuid4()

    line_type = tuple[UUID, UUID, Decimal | str | int, Decimal | str | int, Decimal | str | int, UUID | None]

    def create(lines: tuple[line_type, ...]) -> SalesOrder:
        return SalesOrder.create_from_quote(
            company_id=company_id,
            number="SO-0002",
            source_quote_id=source_quote_id,
            source_quote_revision_number=1,
            customer_id=customer_id,
            seller_id=seller_id,
            currency="BRL",
            lines=lines,
        )

    with pytest.raises(ValueError, match="at least one"):
        create(())
    with pytest.raises(ValueError, match="only once"):
        create(
            (
                (uuid4(), product_id, "1", "10", "0", None),
                (uuid4(), product_id, "1", "10", "0", None),
            )
        )
