"""M9 pricing domain invariants."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.pricing.domain import (
    Money,
    Percentage,
    PriceList,
    PriceListItem,
    PriceListVersion,
    PriceListVersionStatus,
    PriceType,
)


def test_price_list_normalizes_business_keys_and_starts_active() -> None:
    company_id = uuid4()

    price_list = PriceList.create(
        company_id=company_id,
        code=" varejo ",
        name="Varejo Nacional",
        price_type=PriceType.BASE,
    )

    assert price_list.company_id == company_id
    assert price_list.code == "VAREJO"
    assert price_list.currency == "BRL"
    assert price_list.version == 1


def test_price_list_item_enforces_minimum_price_not_above_price() -> None:
    with pytest.raises(ValueError, match="minimum price"):
        PriceListItem.create(
            company_id=uuid4(),
            version_id=uuid4(),
            product_id=uuid4(),
            price=Money.brl("10.00"),
            minimum_price=Money.brl("10.01"),
        )


def test_draft_version_can_activate_only_with_items() -> None:
    company_id, price_list_id, product_id = uuid4(), uuid4(), uuid4()
    draft = PriceListVersion.draft(
        company_id=company_id,
        price_list_id=price_list_id,
        version_number=1,
        valid_from=date(2026, 9, 13),
    )

    with pytest.raises(ValueError, match="without items"):
        draft.activate(datetime(2026, 9, 13, 12, tzinfo=UTC))

    item = PriceListItem.create(
        company_id=company_id,
        version_id=uuid4(),
        product_id=product_id,
        price=Money.brl("19.995"),
        minimum_price=Money.brl("15"),
        target_margin=Percentage.ratio(Decimal("0.35001")),
    )
    ready = PriceListVersion.draft(
        company_id=company_id,
        price_list_id=price_list_id,
        version_number=1,
        valid_from=date(2026, 9, 13),
        items=(item,),
    )

    active = ready.activate(datetime(2026, 9, 13, 12, tzinfo=UTC))

    assert active.status is PriceListVersionStatus.ACTIVE
    assert active.items[0].version_id == ready.id
    assert active.items[0].price.amount == Decimal("20.00")
    assert active.items[0].target_margin is not None
    assert active.items[0].target_margin.value == Decimal("0.3500")
    assert active.version == 2


def test_active_version_can_be_superseded_once() -> None:
    company_id, price_list_id = uuid4(), uuid4()
    item = PriceListItem.create(
        company_id=company_id,
        version_id=uuid4(),
        product_id=uuid4(),
        price=Money.brl("24.90"),
    )
    active = PriceListVersion.draft(
        company_id=company_id,
        price_list_id=price_list_id,
        version_number=1,
        valid_from=date(2026, 9, 13),
        items=(item,),
    ).activate(datetime(2026, 9, 13, 12, tzinfo=UTC))

    superseded = active.supersede()

    assert superseded.status is PriceListVersionStatus.SUPERSEDED
    assert superseded.version == 3
    with pytest.raises(ValueError, match="only active"):
        superseded.supersede()
