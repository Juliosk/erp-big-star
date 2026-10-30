"""Pure Cash Flow value-object, aggregation and governance coverage."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.domain import (
    CashAmount,
    CashFlowCategory,
    CashFlowCertainty,
    CashFlowCurrencyMismatchError,
    CashFlowDateHorizon,
    CashFlowDirection,
    CashFlowHorizonKind,
    CashFlowItem,
    CashFlowMissingSource,
    CashFlowOrigin,
    CashFlowPolicy,
    CashFlowScopeError,
    CashFlowSourceGap,
    CashFlowSummary,
    HypotheticalCashFlowError,
    InvalidCashFlowError,
    LiquidityState,
)

COMPANY_ID = UUID("11111111-1111-4111-8111-111111111111")
REFERENCE_ID = UUID("22222222-2222-4222-8222-222222222222")
HORIZON = CashFlowDateHorizon(date(2026, 11, 1), date(2027, 1, 30))


def _item(
    *,
    amount: str = "100.00",
    direction: CashFlowDirection = CashFlowDirection.INFLOW,
    certainty: CashFlowCertainty = CashFlowCertainty.REALIZED,
    origin: CashFlowOrigin = CashFlowOrigin.BANK_RECONCILIATION,
    reference_id: UUID | None = REFERENCE_ID,
    company_id: UUID = COMPANY_ID,
    occurs_on: date = date(2026, 11, 15),
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


def _gap(
    *,
    company_id: UUID = COMPANY_ID,
    horizon: CashFlowDateHorizon = HORIZON,
) -> CashFlowSourceGap:
    return CashFlowSourceGap(
        company_id=company_id,
        source=CashFlowMissingSource.RECEIVABLES,
        horizon=horizon,
        reason="  M13 ainda não fornece parcelas a receber autoritativas.  ",
    )


def _aggregate(
    *,
    opening: str = "100.00",
    reserve: str = "50.00",
    items: tuple[CashFlowItem, ...] = (),
    gaps: tuple[CashFlowSourceGap, ...] = (),
) -> CashFlowSummary:
    return CashFlowPolicy().aggregate(
        company_id=COMPANY_ID,
        horizon=HORIZON,
        opening_balance=CashAmount(Decimal(opening)),
        minimum_reserve=CashAmount(Decimal(reserve)),
        items=items,
        source_gaps=gaps,
    )


def test_cash_amount_is_exact_normalized_and_immutable() -> None:
    amount = CashAmount(Decimal("12.30"), " brl ")
    assert amount.amount == Decimal("12.30")
    assert amount.currency == "BRL"
    assert amount.require_positive("flow") is amount
    with pytest.raises(FrozenInstanceError):
        amount.amount = Decimal("1.00")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("amount", "currency", "message"),
    [
        (cast(Any, 1.0), "BRL", "finite Decimal"),
        (Decimal("NaN"), "BRL", "finite Decimal"),
        (Decimal("1E+999999"), "BRL", "unsupported"),
        (Decimal("1.001"), "BRL", "two decimal"),
        (Decimal("1.00"), cast(Any, 986), "currency must be text"),
        (Decimal("1.00"), "R$", "ISO 4217"),
    ],
)
def test_cash_amount_rejects_imprecise_or_untyped_values(
    amount: Decimal, currency: str, message: str
) -> None:
    with pytest.raises(InvalidCashFlowError, match=message):
        CashAmount(amount, currency)


def test_cash_amount_positive_gate_rejects_zero_and_negative() -> None:
    for value in (Decimal("0.00"), Decimal("-0.01")):
        with pytest.raises(InvalidCashFlowError, match="flow must be positive"):
            CashAmount(value).require_positive("flow")


def test_date_horizon_classifies_short_medium_and_long_term() -> None:
    assert HORIZON.kind is CashFlowHorizonKind.SHORT_TERM
    medium = CashFlowDateHorizon(date(2026, 1, 1), date(2026, 4, 2))
    long = CashFlowDateHorizon(date(2026, 1, 1), date(2027, 1, 2))
    assert medium.kind is CashFlowHorizonKind.MEDIUM_TERM
    assert long.kind is CashFlowHorizonKind.LONG_TERM
    assert HORIZON.contains(date(2026, 11, 1))
    assert HORIZON.contains(date(2027, 1, 30))
    assert not HORIZON.contains(date(2027, 1, 31))


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (cast(Any, "2026-01-01"), date(2026, 1, 1), "start_on"),
        (date(2026, 1, 1), cast(Any, datetime(2026, 1, 2, tzinfo=UTC)), "end_on"),
        (date(2026, 1, 2), date(2026, 1, 1), "cannot precede"),
    ],
)
def test_date_horizon_rejects_invalid_dates(start: date, end: date, message: str) -> None:
    with pytest.raises(InvalidCashFlowError, match=message):
        CashFlowDateHorizon(start, end)
    with pytest.raises(InvalidCashFlowError, match="value must be a date"):
        HORIZON.contains(cast(date, "2026-11-01"))


def test_cash_flow_items_accept_only_authoritative_certainty_origin_pairs() -> None:
    realized = _item()
    payable = _item(
        certainty=CashFlowCertainty.COMMITTED,
        origin=CashFlowOrigin.PAYABLE_INSTALLMENT,
    )
    receivable = replace(payable, origin=CashFlowOrigin.RECEIVABLE_INSTALLMENT)
    scenario = _item(
        certainty=CashFlowCertainty.SCENARIO,
        origin=CashFlowOrigin.MANUAL_SCENARIO,
        reference_id=None,
    )
    assert realized.certainty is CashFlowCertainty.REALIZED
    assert payable.origin is CashFlowOrigin.PAYABLE_INSTALLMENT
    assert receivable.origin is CashFlowOrigin.RECEIVABLE_INSTALLMENT
    assert scenario.reference_id is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"company_id": UUID(int=0)}, "company_id"),
        ({"amount": object()}, "CashAmount"),
        ({"amount": CashAmount(Decimal("0.00"))}, "positive"),
        ({"occurs_on": "2026-11-15"}, "occurs_on"),
        ({"direction": "INFLOW"}, "CashFlowDirection"),
        ({"category": "OPERATING"}, "CashFlowCategory"),
        ({"certainty": "REALIZED"}, "CashFlowCertainty"),
        ({"origin": "BANK_RECONCILIATION"}, "CashFlowOrigin"),
        ({"origin": CashFlowOrigin.PAYABLE_INSTALLMENT}, "not authoritative"),
        ({"reference_id": None}, "require reference_id"),
        ({"reference_id": UUID(int=0)}, "reference_id"),
    ],
)
def test_cash_flow_item_invariants(changes: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidCashFlowError, match=message):
        replace(_item(), **cast(Any, changes))


def test_hypothetical_fiscal_billing_is_forbidden_even_in_scenarios() -> None:
    with pytest.raises(HypotheticalCashFlowError, match="not cash authority"):
        _item(origin=CashFlowOrigin.FISCAL_BILLING)
    with pytest.raises(InvalidCashFlowError, match="cannot impersonate"):
        _item(
            certainty=CashFlowCertainty.SCENARIO,
            origin=CashFlowOrigin.MANUAL_SCENARIO,
        )


def test_source_gap_is_explicit_normalized_and_immutable() -> None:
    gap = _gap()
    assert gap.source is CashFlowMissingSource.RECEIVABLES
    assert gap.reason == "M13 ainda não fornece parcelas a receber autoritativas."
    with pytest.raises(FrozenInstanceError):
        gap.reason = "ocultar"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"company_id": UUID(int=0)}, "company_id"),
        ({"source": "RECEIVABLES"}, "CashFlowMissingSource"),
        ({"horizon": object()}, "CashFlowDateHorizon"),
        ({"reason": 1}, "reason must be text"),
        ({"reason": " "}, "between 1 and 500"),
        ({"reason": "x" * 501}, "between 1 and 500"),
    ],
)
def test_source_gap_invariants(changes: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidCashFlowError, match=message):
        replace(_gap(), **cast(Any, changes))


def test_policy_aggregates_all_buckets_and_keeps_scenario_separate() -> None:
    items = (
        _item(amount="50.00"),
        _item(amount="10.00", direction=CashFlowDirection.OUTFLOW),
        _item(
            amount="40.00",
            certainty=CashFlowCertainty.COMMITTED,
            origin=CashFlowOrigin.RECEIVABLE_INSTALLMENT,
        ),
        _item(
            amount="30.00",
            direction=CashFlowDirection.OUTFLOW,
            certainty=CashFlowCertainty.COMMITTED,
            origin=CashFlowOrigin.PAYABLE_INSTALLMENT,
        ),
        _item(
            amount="1000.00",
            certainty=CashFlowCertainty.SCENARIO,
            origin=CashFlowOrigin.MANUAL_SCENARIO,
            reference_id=None,
        ),
        _item(
            amount="200.00",
            direction=CashFlowDirection.OUTFLOW,
            certainty=CashFlowCertainty.SCENARIO,
            origin=CashFlowOrigin.MANUAL_SCENARIO,
            reference_id=None,
        ),
    )
    result = _aggregate(items=items)
    assert result.realized_inflows.amount == Decimal("50.00")
    assert result.realized_outflows.amount == Decimal("10.00")
    assert result.committed_inflows.amount == Decimal("40.00")
    assert result.committed_outflows.amount == Decimal("30.00")
    assert result.scenario_inflows.amount == Decimal("1000.00")
    assert result.scenario_outflows.amount == Decimal("200.00")
    assert result.operational_closing_balance.amount == Decimal("150.00")
    assert result.scenario_closing_balance.amount == Decimal("950.00")
    assert result.liquidity_state is LiquidityState.HEALTHY
    assert result.currency == "BRL"


@pytest.mark.parametrize(
    ("opening", "reserve", "gaps", "expected"),
    [
        ("100.00", "50.00", (), LiquidityState.HEALTHY),
        ("10.00", "50.00", (), LiquidityState.ATTENTION),
        ("-0.01", "50.00", (), LiquidityState.CRITICAL),
        ("100.00", "50.00", (_gap(),), LiquidityState.INCOMPLETE),
    ],
)
def test_policy_classifies_liquidity_fail_closed(
    opening: str,
    reserve: str,
    gaps: tuple[CashFlowSourceGap, ...],
    expected: LiquidityState,
) -> None:
    result = _aggregate(opening=opening, reserve=reserve, gaps=gaps)
    assert result.liquidity_state is expected
    assert result.source_gaps == gaps


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"company_id": UUID(int=0)}, InvalidCashFlowError, "company_id"),
        ({"horizon": object()}, InvalidCashFlowError, "horizon"),
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
            {"items": (_item(occurs_on=date(2027, 2, 1)),)},
            InvalidCashFlowError,
            "outside",
        ),
        ({"source_gaps": (object(),)}, InvalidCashFlowError, "CashFlowSourceGap"),
        (
            {"source_gaps": (_gap(company_id=uuid4()),)},
            CashFlowScopeError,
            "another company",
        ),
        (
            {
                "source_gaps": (
                    _gap(horizon=CashFlowDateHorizon(date(2026, 11, 2), date(2027, 1, 29))),
                )
            },
            InvalidCashFlowError,
            "cover",
        ),
    ],
)
def test_policy_rejects_scope_currency_horizon_and_type_violations(
    kwargs: dict[str, object], error: type[Exception], message: str
) -> None:
    arguments: dict[str, object] = {
        "company_id": COMPANY_ID,
        "horizon": HORIZON,
        "opening_balance": CashAmount(Decimal("100.00")),
        "minimum_reserve": CashAmount(Decimal("50.00")),
        "items": (),
        "source_gaps": (),
    }
    arguments.update(kwargs)
    with pytest.raises(error, match=message):
        CashFlowPolicy().aggregate(**cast(Any, arguments))


def test_cash_flow_adr_freezes_boundaries_rbac_and_no_hypothetical_billing() -> None:
    content = Path("docs/adr/0181-cash-flow-liquidity-projections.md").read_text(encoding="utf-8")
    for term in (
        "finance.cash_flow.read",
        "finance.cash_flow.project",
        "finance.cash_flow.scenario",
        "CashFlowSourceGap",
        "FISCAL_BILLING",
        "M13",
        "INCOMPLETE",
        "Decimal",
    ):
        assert term in content


__all__: list[str] = []
