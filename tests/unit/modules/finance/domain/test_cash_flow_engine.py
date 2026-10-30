"""Cash Flow aggregate, scenario and deterministic-engine coverage."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.domain import (
    BusinessCalendar,
    BusinessDayConvention,
    CashAmount,
    CashFlowCategory,
    CashFlowCertainty,
    CashFlowCurrencyMismatchError,
    CashFlowDateHorizon,
    CashFlowDirection,
    CashFlowEngine,
    CashFlowItem,
    CashFlowMissingSource,
    CashFlowOrigin,
    CashFlowPolicy,
    CashFlowProjectionInput,
    CashFlowScenario,
    CashFlowScopeError,
    CashFlowSourceGap,
    InvalidCashFlowError,
    LiquidityState,
    ProjectionGranularity,
)

COMPANY_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PROJECTION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
SCENARIO_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
REFERENCE_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
NOW = datetime(2026, 1, 1, 8, tzinfo=UTC)
HORIZON = CashFlowDateHorizon(date(2026, 1, 1), date(2026, 1, 10))


def _scenario(
    *,
    delay: int = 0,
    cost_rate: str = "0.0000",
    convention: BusinessDayConvention = BusinessDayConvention.FOLLOWING,
) -> CashFlowScenario:
    return CashFlowScenario(
        id=SCENARIO_ID,
        name="  Cenário Base  ",
        receivable_delay_days=delay,
        cost_variation_rate=Decimal(cost_rate),
        business_day_convention=convention,
    )


def _item(
    *,
    amount: str = "100.00",
    occurs_on: date = date(2026, 1, 2),
    direction: CashFlowDirection = CashFlowDirection.INFLOW,
    certainty: CashFlowCertainty = CashFlowCertainty.REALIZED,
    origin: CashFlowOrigin = CashFlowOrigin.BANK_RECONCILIATION,
    reference_id: UUID | None = REFERENCE_ID,
    company_id: UUID = COMPANY_ID,
    currency: str = "BRL",
) -> CashFlowItem:
    return CashFlowItem(
        company_id=company_id,
        amount=CashAmount(Decimal(amount), currency),
        occurs_on=occurs_on,
        direction=direction,
        category=CashFlowCategory.OPERATING,
        certainty=certainty,
        origin=origin,
        reference_id=reference_id,
    )


def _request(
    *,
    horizon: CashFlowDateHorizon = HORIZON,
    granularity: ProjectionGranularity = ProjectionGranularity.DAILY,
    scenario: CashFlowScenario | None = None,
    items: tuple[CashFlowItem, ...] = (),
    gaps: tuple[CashFlowSourceGap, ...] = (),
) -> CashFlowProjectionInput:
    return CashFlowProjectionInput(
        projection_id=PROJECTION_ID,
        company_id=COMPANY_ID,
        as_of=horizon.start_on,
        calculated_at=NOW,
        horizon=horizon,
        granularity=granularity,
        opening_balance=CashAmount(Decimal("1000.00")),
        minimum_reserve=CashAmount(Decimal("100.00")),
        scenario=scenario or _scenario(),
        items=items,
        source_gaps=gaps,
    )


def _gap(*, company_id: UUID = COMPANY_ID) -> CashFlowSourceGap:
    return CashFlowSourceGap(
        company_id=company_id,
        source=CashFlowMissingSource.RECEIVABLES,
        horizon=HORIZON,
        reason="Autoridade M13 indisponível.",
    )


def test_business_calendar_adjusts_holidays_and_weekends_deterministically() -> None:
    calendar = BusinessCalendar(holidays=frozenset({date(2026, 1, 5)}))
    assert calendar.is_business_day(date(2026, 1, 2))
    assert not calendar.is_business_day(date(2026, 1, 3))
    assert not calendar.is_business_day(date(2026, 1, 5))
    assert calendar.adjust(date(2026, 1, 3), BusinessDayConvention.FOLLOWING) == date(
        2026, 1, 6
    )
    assert calendar.adjust(date(2026, 1, 4), BusinessDayConvention.PRECEDING) == date(
        2026, 1, 2
    )
    assert calendar.adjust(date(2026, 1, 3), BusinessDayConvention.UNADJUSTED) == date(
        2026, 1, 3
    )
    assert calendar.adjust(date(2026, 1, 2), BusinessDayConvention.FOLLOWING) == date(
        2026, 1, 2
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"holidays": {date(2026, 1, 1)}}, "frozenset of dates"),
        ({"holidays": frozenset({cast(date, "2026-01-01")})}, "frozenset of dates"),
        ({"weekend_days": {5, 6}}, "business weekday"),
        ({"weekend_days": frozenset()}, "business weekday"),
        ({"weekend_days": frozenset(range(7))}, "business weekday"),
        ({"weekend_days": frozenset({True, 6})}, "business weekday"),
        ({"weekend_days": frozenset({5, 7})}, "business weekday"),
    ],
)
def test_business_calendar_rejects_invalid_configuration(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidCashFlowError, match=message):
        BusinessCalendar(**cast(Any, kwargs))


def test_business_calendar_rejects_untyped_inputs() -> None:
    calendar = BusinessCalendar()
    with pytest.raises(InvalidCashFlowError, match="value must be a date"):
        calendar.is_business_day(cast(date, "2026-01-01"))
    with pytest.raises(InvalidCashFlowError, match="BusinessDayConvention"):
        calendar.adjust(date(2026, 1, 1), cast(BusinessDayConvention, "FOLLOWING"))


def test_scenario_is_normalized_and_immutable() -> None:
    scenario = _scenario(delay=7, cost_rate="0.1250")
    assert scenario.name == "Cenário Base"
    assert scenario.receivable_delay_days == 7
    assert scenario.cost_variation_rate == Decimal("0.1250")
    with pytest.raises(FrozenInstanceError):
        scenario.name = "alterado"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": UUID(int=0)}, "scenario.id"),
        ({"name": 1}, "must be text"),
        ({"name": " "}, "between 1 and 120"),
        ({"name": "x" * 121}, "between 1 and 120"),
        ({"receivable_delay_days": True}, "between 0 and 365"),
        ({"receivable_delay_days": -1}, "between 0 and 365"),
        ({"receivable_delay_days": 366}, "between 0 and 365"),
        ({"cost_variation_rate": cast(Any, 0.1)}, "finite Decimal"),
        ({"cost_variation_rate": Decimal("NaN")}, "finite Decimal"),
        ({"cost_variation_rate": Decimal("1E+999999")}, "unsupported precision"),
        ({"cost_variation_rate": Decimal("0.00001")}, "four decimals"),
        ({"cost_variation_rate": Decimal("10.0001")}, "four decimals"),
        ({"business_day_convention": "FOLLOWING"}, "BusinessDayConvention"),
    ],
)
def test_scenario_invariants(changes: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidCashFlowError, match=message):
        replace(_scenario(), **cast(Any, changes))


def test_projection_input_is_tenant_currency_and_horizon_bound() -> None:
    item = _item()
    request = _request(items=(item,))
    assert request.company_id == COMPANY_ID
    assert request.items == (item,)
    assert request.version == 1


@pytest.mark.parametrize(
    ("changes", "error", "message"),
    [
        ({"projection_id": UUID(int=0)}, InvalidCashFlowError, "projection_id"),
        ({"company_id": UUID(int=0)}, InvalidCashFlowError, "company_id"),
        ({"calculated_at": "now"}, InvalidCashFlowError, "timezone-aware"),
        ({"calculated_at": NOW.replace(tzinfo=None)}, InvalidCashFlowError, "timezone-aware"),
        ({"horizon": object()}, InvalidCashFlowError, "CashFlowDateHorizon"),
        ({"as_of": date(2025, 12, 31)}, InvalidCashFlowError, "start on as_of"),
        ({"granularity": "DAILY"}, InvalidCashFlowError, "ProjectionGranularity"),
        ({"opening_balance": object()}, InvalidCashFlowError, "opening_balance"),
        ({"minimum_reserve": object()}, InvalidCashFlowError, "minimum_reserve"),
        (
            {"minimum_reserve": CashAmount(Decimal("1.00"), "USD")},
            CashFlowCurrencyMismatchError,
            "one currency",
        ),
        (
            {"minimum_reserve": CashAmount(Decimal("-1.00"))},
            InvalidCashFlowError,
            "cannot be negative",
        ),
        ({"scenario": object()}, InvalidCashFlowError, "CashFlowScenario"),
        ({"items": []}, InvalidCashFlowError, "immutable tuple"),
        ({"items": (object(),)}, InvalidCashFlowError, "CashFlowItem"),
        (
            {"items": (_item(company_id=uuid4()),)},
            CashFlowScopeError,
            "another company",
        ),
        (
            {"items": (_item(currency="USD"),)},
            CashFlowCurrencyMismatchError,
            "another currency",
        ),
        (
            {"items": (_item(occurs_on=date(2026, 1, 11)),)},
            InvalidCashFlowError,
            "outside",
        ),
        ({"source_gaps": []}, InvalidCashFlowError, "immutable tuple"),
        ({"source_gaps": (object(),)}, InvalidCashFlowError, "CashFlowSourceGap"),
        (
            {"source_gaps": (_gap(company_id=uuid4()),)},
            CashFlowScopeError,
            "another company",
        ),
        (
            {
                "source_gaps": (
                    replace(
                        _gap(),
                        horizon=CashFlowDateHorizon(date(2026, 1, 2), date(2026, 1, 9)),
                    ),
                )
            },
            InvalidCashFlowError,
            "cover",
        ),
        ({"version": True}, InvalidCashFlowError, "positive integer"),
        ({"version": 0}, InvalidCashFlowError, "positive integer"),
    ],
)
def test_projection_input_invariants(
    changes: dict[str, object], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        replace(_request(), **cast(Any, changes))


def test_daily_projection_consolidates_authoritative_cash_and_isolates_scenario() -> None:
    realized = _item(amount="50.00")
    payable = _item(
        occurs_on=date(2026, 1, 3),
        direction=CashFlowDirection.OUTFLOW,
        certainty=CashFlowCertainty.COMMITTED,
        origin=CashFlowOrigin.PAYABLE_INSTALLMENT,
    )
    receivable = _item(
        amount="200.00",
        certainty=CashFlowCertainty.COMMITTED,
        origin=CashFlowOrigin.RECEIVABLE_INSTALLMENT,
    )
    manual = _item(
        amount="20.00",
        occurs_on=date(2026, 1, 4),
        direction=CashFlowDirection.OUTFLOW,
        certainty=CashFlowCertainty.SCENARIO,
        origin=CashFlowOrigin.MANUAL_SCENARIO,
        reference_id=None,
    )
    request = _request(
        scenario=_scenario(delay=3, cost_rate="0.1000"),
        items=(realized, payable, receivable, manual),
    )
    projection = CashFlowEngine(BusinessCalendar()).project(request)

    assert projection.source_items == request.items
    assert len(projection.buckets) == 10
    assert projection.buckets[0].start_on == date(2026, 1, 1)
    assert projection.buckets[-1].end_on == date(2026, 1, 10)
    assert projection.summary.operational_closing_balance.amount == Decimal("1150.00")
    assert projection.summary.scenario_closing_balance.amount == Decimal("1120.00")
    assert projection.liquidity_state is LiquidityState.HEALTHY
    assert projection.deferred_items == ()
    assert projection.buckets[-1].scenario_closing_balance.amount == Decimal("1120.00")
    assert projection.buckets[-1].operational_closing_balance.amount == Decimal("1150.00")
    assert payable.occurs_on == date(2026, 1, 3)
    assert any(item.occurs_on == date(2026, 1, 5) for item in projection.projected_items)
    with pytest.raises(FrozenInstanceError):
        projection.company_id = uuid4()  # type: ignore[misc]


def test_negative_and_rounding_zero_cost_variations_are_scenario_only() -> None:
    payable = _item(
        amount="100.00",
        direction=CashFlowDirection.OUTFLOW,
        certainty=CashFlowCertainty.COMMITTED,
        origin=CashFlowOrigin.PAYABLE_INSTALLMENT,
    )
    reduced = CashFlowEngine(BusinessCalendar()).project(
        _request(scenario=_scenario(cost_rate="-0.2500"), items=(payable,))
    )
    assert reduced.summary.operational_closing_balance.amount == Decimal("900.00")
    assert reduced.summary.scenario_inflows.amount == Decimal("25.00")
    assert reduced.summary.scenario_closing_balance.amount == Decimal("925.00")

    tiny = replace(payable, amount=CashAmount(Decimal("0.01")))
    rounded = CashFlowEngine(BusinessCalendar()).project(
        _request(scenario=_scenario(cost_rate="0.0001"), items=(tiny,))
    )
    assert rounded.summary.scenario_outflows.amount == Decimal("0.00")


def test_delayed_receivable_outside_horizon_is_exposed_as_deferred() -> None:
    receivable = _item(
        amount="200.00",
        occurs_on=date(2026, 1, 9),
        certainty=CashFlowCertainty.COMMITTED,
        origin=CashFlowOrigin.RECEIVABLE_INSTALLMENT,
    )
    projection = CashFlowEngine(BusinessCalendar()).project(
        _request(scenario=_scenario(delay=10), items=(receivable,))
    )
    assert len(projection.deferred_items) == 1
    assert projection.deferred_items[0].occurs_on == date(2026, 1, 19)
    assert projection.summary.operational_closing_balance.amount == Decimal("1200.00")
    assert projection.summary.scenario_closing_balance.amount == Decimal("1000.00")


def test_source_gap_marks_every_bucket_incomplete_without_inventing_receivables() -> None:
    projection = CashFlowEngine(BusinessCalendar()).project(_request(gaps=(_gap(),)))
    assert projection.projected_items == ()
    assert projection.summary.source_gaps == (_gap(),)
    assert projection.liquidity_state is LiquidityState.INCOMPLETE
    assert all(bucket.liquidity_state is LiquidityState.INCOMPLETE for bucket in projection.buckets)
    assert projection.summary.operational_closing_balance.amount == Decimal("1000.00")


def test_weekly_and_monthly_periods_use_calendar_boundaries() -> None:
    weekly_horizon = CashFlowDateHorizon(date(2026, 1, 1), date(2026, 1, 20))
    weekly = CashFlowEngine(BusinessCalendar()).project(
        _request(horizon=weekly_horizon, granularity=ProjectionGranularity.WEEKLY)
    )
    assert [(bucket.start_on, bucket.end_on) for bucket in weekly.buckets] == [
        (date(2026, 1, 1), date(2026, 1, 4)),
        (date(2026, 1, 5), date(2026, 1, 11)),
        (date(2026, 1, 12), date(2026, 1, 18)),
        (date(2026, 1, 19), date(2026, 1, 20)),
    ]

    monthly_horizon = CashFlowDateHorizon(date(2026, 11, 15), date(2027, 2, 3))
    monthly = CashFlowEngine(BusinessCalendar()).project(
        _request(horizon=monthly_horizon, granularity=ProjectionGranularity.MONTHLY)
    )
    assert [(bucket.start_on, bucket.end_on) for bucket in monthly.buckets] == [
        (date(2026, 11, 15), date(2026, 11, 30)),
        (date(2026, 12, 1), date(2026, 12, 31)),
        (date(2027, 1, 1), date(2027, 1, 31)),
        (date(2027, 2, 1), date(2027, 2, 3)),
    ]


def test_preceding_and_unadjusted_conventions_are_applied_to_commitments() -> None:
    payable = _item(
        occurs_on=date(2026, 1, 3),
        direction=CashFlowDirection.OUTFLOW,
        certainty=CashFlowCertainty.COMMITTED,
        origin=CashFlowOrigin.PAYABLE_INSTALLMENT,
    )
    preceding = CashFlowEngine(BusinessCalendar()).project(
        _request(scenario=_scenario(convention=BusinessDayConvention.PRECEDING), items=(payable,))
    )
    unadjusted = CashFlowEngine(BusinessCalendar()).project(
        _request(scenario=_scenario(convention=BusinessDayConvention.UNADJUSTED), items=(payable,))
    )
    assert preceding.projected_items[0].occurs_on == date(2026, 1, 2)
    assert unadjusted.projected_items[0].occurs_on == date(2026, 1, 3)


def test_engine_is_deterministic_and_validates_composed_dependencies() -> None:
    request = _request(items=(_item(),))
    engine = CashFlowEngine(BusinessCalendar())
    assert engine.project(request) == engine.project(request)
    with pytest.raises(InvalidCashFlowError, match="calendar"):
        CashFlowEngine(cast(BusinessCalendar, object()))
    with pytest.raises(InvalidCashFlowError, match="policy"):
        CashFlowEngine(BusinessCalendar(), cast(CashFlowPolicy, object()))
    with pytest.raises(InvalidCashFlowError, match="request"):
        engine.project(cast(CashFlowProjectionInput, object()))


def test_projection_aggregate_rejects_corrupt_bucket_and_summary_scope() -> None:
    projection = CashFlowEngine(BusinessCalendar()).project(_request())
    with pytest.raises(InvalidCashFlowError, match="at least one bucket"):
        replace(projection, buckets=())
    first = projection.buckets[0]
    with pytest.raises(InvalidCashFlowError, match="first bucket"):
        replace(projection, buckets=(replace(first, start_on=date(2025, 12, 31)),))
    with pytest.raises(InvalidCashFlowError, match="last bucket"):
        replace(projection, buckets=(replace(first, end_on=date(2026, 1, 9)),))
    broken = (
        first,
        replace(
            projection.buckets[1],
            start_on=date(2026, 1, 4),
            end_on=date(2026, 1, 4),
        ),
    )
    with pytest.raises(InvalidCashFlowError, match="contiguous"):
        replace(
            projection,
            horizon=CashFlowDateHorizon(date(2026, 1, 1), date(2026, 1, 4)),
            buckets=broken,
        )
    with pytest.raises(CashFlowScopeError, match="summary"):
        replace(projection, summary=replace(projection.summary, company_id=uuid4()))


__all__: list[str] = []
