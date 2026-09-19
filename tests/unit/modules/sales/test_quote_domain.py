"""M15 quote rules remain pure and framework independent."""

from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.sales.domain import SalesQuote, SalesQuoteStatus


def quote() -> SalesQuote:
    return SalesQuote.create(
        company_id=uuid4(),
        number="qte-001",
        customer_id=uuid4(),
        seller_id=uuid4(),
    )


def test_quote_revision_freezes_items_totals_and_pricing_refs() -> None:
    draft = quote()
    product_id = uuid4()
    snapshot_id = uuid4()
    revised, revision = draft.revise(
        lines=((product_id, "2.500000", "20.00", "5.00"),),
        pricing_snapshot_refs=(snapshot_id,),
    )

    assert revised.current_revision_number == 1
    assert revised.version == 2
    assert revision.quote_id == draft.id
    assert revision.items[0].quantity == Decimal("2.500000")
    assert revision.gross_amount == Decimal("50.00")
    assert revision.discount_amount == Decimal("5.00")
    assert revision.net_amount == Decimal("45.00")
    assert revision.pricing_snapshot_refs == (snapshot_id,)


def test_quote_lifecycle_requires_revision_acceptance_and_no_reversal() -> None:
    draft = quote()
    with pytest.raises(ValueError, match="revised draft"):
        draft.send()

    revised, _ = draft.revise(lines=((uuid4(), 1, "100.00", 0),))
    sent = revised.send()
    accepted = sent.accept()
    converted = accepted.convert(uuid4())

    assert sent.status is SalesQuoteStatus.SENT
    assert accepted.status is SalesQuoteStatus.ACCEPTED
    assert converted.status is SalesQuoteStatus.CONVERTED
    assert converted.converted_order_id is not None
    with pytest.raises(ValueError, match="accepted"):
        converted.convert(uuid4())


def test_quote_rejects_duplicate_products_invalid_discount_and_revision_after_send() -> None:
    draft = quote()
    product_id = uuid4()
    with pytest.raises(ValueError, match="only once"):
        draft.revise(
            lines=(
                (product_id, 1, "10.00", 0),
                (product_id, 2, "10.00", 0),
            )
        )
    with pytest.raises(ValueError, match="exceed"):
        draft.revise(lines=((uuid4(), 1, "10.00", "10.01"),))
    revised, _ = draft.revise(lines=((uuid4(), 1, "10.00", 0),))
    with pytest.raises(ValueError, match="draft"):
        revised.send().revise(lines=((uuid4(), 1, "10.00", 0),))
