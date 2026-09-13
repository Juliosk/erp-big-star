"""Pure M9 profitability policy rules."""

from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.pricing.domain import (
    LEGACY_OPENING,
    MinimumMarginPolicy,
    Money,
    Percentage,
    StandardCostSeed,
    ensure_minimum_margin,
    profitability_margin,
)


def test_standard_cost_seed_is_legacy_opening_and_margin_is_calculated() -> None:
    company_id = uuid4()
    product_id = uuid4()
    seed = StandardCostSeed.create(
        company_id=company_id, product_id=product_id, cost=Money.brl("60.00")
    )
    policy = MinimumMarginPolicy.create(
        company_id=company_id,
        code="default",
        name="Default margin",
        minimum_margin=Percentage.ratio("0.3000"),
    )

    assert seed.source == LEGACY_OPENING
    assert profitability_margin(price=Money.brl("100.00"), cost=seed.cost).value == Decimal(
        "0.4000"
    )
    assert ensure_minimum_margin(
        price=Money.brl("100.00"), cost=seed, policy=policy
    ).value == Decimal("0.4000")


def test_minimum_margin_rejects_unprofitable_price() -> None:
    company_id = uuid4()
    seed = StandardCostSeed.create(
        company_id=company_id, product_id=uuid4(), cost=Money.brl("80.00")
    )
    policy = MinimumMarginPolicy.create(
        company_id=company_id,
        code="default",
        name="Default margin",
        minimum_margin=Percentage.ratio("0.3000"),
    )

    with pytest.raises(ValueError, match="minimum margin"):
        ensure_minimum_margin(price=Money.brl("100.00"), cost=seed, policy=policy)
