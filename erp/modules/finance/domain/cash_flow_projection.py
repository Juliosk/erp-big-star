"""Immutable Cash Flow projection aggregate and deterministic engine."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from erp.modules.finance.domain.cash_flow import (
    CashAmount,
    CashFlowCertainty,
    CashFlowDateHorizon,
    CashFlowDirection,
    CashFlowItem,
    CashFlowOrigin,
    CashFlowPolicy,
    CashFlowSourceGap,
    CashFlowSummary,
    LiquidityState,
)
from erp.modules.finance.domain.exceptions import (
    CashFlowCurrencyMismatchError,
    CashFlowScopeError,
    InvalidCashFlowError,
)

_RATE = Decimal("0.0001")
_CENT = Decimal("0.01")


def _uuid(value: UUID, field_name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidCashFlowError(f"{field_name} must be a non-zero UUID.")
    return value


def _date(value: date, field_name: str) -> date:
    if type(value) is not date:
        raise InvalidCashFlowError(f"{field_name} must be a date.")
    return value


def _text(value: str, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidCashFlowError(f"{field_name} must be text.")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise InvalidCashFlowError(
            f"{field_name} must contain between 1 and {maximum} characters."
        )
    return normalized


class ProjectionGranularity(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class BusinessDayConvention(StrEnum):
    FOLLOWING = "FOLLOWING"
    PRECEDING = "PRECEDING"
    UNADJUSTED = "UNADJUSTED"


@dataclass(frozen=True, slots=True)
class BusinessCalendar:
    """Deterministic calendar injected into the engine; no locale or clock access."""

    holidays: frozenset[date] = field(default_factory=frozenset)
    weekend_days: frozenset[int] = field(default_factory=lambda: frozenset({5, 6}))

    def __post_init__(self) -> None:
        if not isinstance(self.holidays, frozenset) or any(
            type(item) is not date for item in self.holidays
        ):
            raise InvalidCashFlowError("holidays must be a frozenset of dates.")
        if (
            not isinstance(self.weekend_days, frozenset)
            or not self.weekend_days
            or len(self.weekend_days) == 7
            or any(type(day) is not int or not 0 <= day <= 6 for day in self.weekend_days)
        ):
            raise InvalidCashFlowError("weekend_days must leave at least one business weekday.")

    def is_business_day(self, value: date) -> bool:
        day = _date(value, "value")
        return day.weekday() not in self.weekend_days and day not in self.holidays

    def adjust(self, value: date, convention: BusinessDayConvention) -> date:
        current = _date(value, "value")
        if not isinstance(convention, BusinessDayConvention):
            raise InvalidCashFlowError("convention must be a BusinessDayConvention.")
        if convention is BusinessDayConvention.UNADJUSTED or self.is_business_day(current):
            return current
        step = 1 if convention is BusinessDayConvention.FOLLOWING else -1
        while not self.is_business_day(current):
            current += timedelta(days=step)
        return current


@dataclass(frozen=True, slots=True)
class CashFlowScenario:
    """Named sensitivity assumptions; zero values form the deterministic baseline."""

    id: UUID
    name: str
    receivable_delay_days: int = 0
    cost_variation_rate: Decimal = Decimal("0.0000")
    business_day_convention: BusinessDayConvention = BusinessDayConvention.FOLLOWING

    def __post_init__(self) -> None:
        _uuid(self.id, "scenario.id")
        object.__setattr__(self, "name", _text(self.name, "scenario.name", maximum=120))
        if (
            type(self.receivable_delay_days) is not int
            or not 0 <= self.receivable_delay_days <= 365
        ):
            raise InvalidCashFlowError("receivable_delay_days must be between 0 and 365.")
        if not isinstance(self.cost_variation_rate, Decimal) or not self.cost_variation_rate.is_finite():
            raise InvalidCashFlowError("cost_variation_rate must be a finite Decimal.")
        try:
            normalized = self.cost_variation_rate.quantize(_RATE)
        except InvalidOperation as error:
            raise InvalidCashFlowError("cost_variation_rate uses unsupported precision.") from error
        if normalized != self.cost_variation_rate or not Decimal("-1") <= normalized <= Decimal("10"):
            raise InvalidCashFlowError(
                "cost_variation_rate must use four decimals and stay between -1 and 10."
            )
        if not isinstance(self.business_day_convention, BusinessDayConvention):
            raise InvalidCashFlowError(
                "business_day_convention must be a BusinessDayConvention."
            )
        object.__setattr__(self, "cost_variation_rate", normalized)


@dataclass(frozen=True, slots=True)
class CashFlowProjectionInput:
    projection_id: UUID
    company_id: UUID
    as_of: date
    calculated_at: datetime
    horizon: CashFlowDateHorizon
    granularity: ProjectionGranularity
    opening_balance: CashAmount
    minimum_reserve: CashAmount
    scenario: CashFlowScenario
    items: tuple[CashFlowItem, ...]
    source_gaps: tuple[CashFlowSourceGap, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        _uuid(self.projection_id, "projection_id")
        _uuid(self.company_id, "company_id")
        _date(self.as_of, "as_of")
        if (
            not isinstance(self.calculated_at, datetime)
            or self.calculated_at.tzinfo is None
            or self.calculated_at.utcoffset() is None
        ):
            raise InvalidCashFlowError("calculated_at must be timezone-aware.")
        if not isinstance(self.horizon, CashFlowDateHorizon):
            raise InvalidCashFlowError("horizon must be a CashFlowDateHorizon.")
        if self.horizon.start_on != self.as_of:
            raise InvalidCashFlowError("horizon must start on as_of.")
        if not isinstance(self.granularity, ProjectionGranularity):
            raise InvalidCashFlowError("granularity must be a ProjectionGranularity.")
        if not isinstance(self.opening_balance, CashAmount):
            raise InvalidCashFlowError("opening_balance must be a CashAmount.")
        if not isinstance(self.minimum_reserve, CashAmount):
            raise InvalidCashFlowError("minimum_reserve must be a CashAmount.")
        if self.opening_balance.currency != self.minimum_reserve.currency:
            raise CashFlowCurrencyMismatchError("opening balance and reserve must use one currency.")
        if self.minimum_reserve.amount < 0:
            raise InvalidCashFlowError("minimum_reserve cannot be negative.")
        if not isinstance(self.scenario, CashFlowScenario):
            raise InvalidCashFlowError("scenario must be a CashFlowScenario.")
        if not isinstance(self.items, tuple):
            raise InvalidCashFlowError("items must be an immutable tuple.")
        for item in self.items:
            if not isinstance(item, CashFlowItem):
                raise InvalidCashFlowError("items must contain CashFlowItem values.")
            if item.company_id != self.company_id:
                raise CashFlowScopeError("cash-flow item belongs to another company.")
            if item.amount.currency != self.opening_balance.currency:
                raise CashFlowCurrencyMismatchError("cash-flow item uses another currency.")
            if not self.horizon.contains(item.occurs_on):
                raise InvalidCashFlowError("cash-flow input item is outside the requested horizon.")
        if not isinstance(self.source_gaps, tuple):
            raise InvalidCashFlowError("source_gaps must be an immutable tuple.")
        for gap in self.source_gaps:
            if not isinstance(gap, CashFlowSourceGap):
                raise InvalidCashFlowError("source_gaps must contain CashFlowSourceGap values.")
            if gap.company_id != self.company_id:
                raise CashFlowScopeError("source gap belongs to another company.")
            if gap.horizon.start_on > self.horizon.start_on or gap.horizon.end_on < self.horizon.end_on:
                raise InvalidCashFlowError("source gap must cover the projection horizon.")
        if type(self.version) is not int or self.version < 1:
            raise InvalidCashFlowError("version must be a positive integer.")


@dataclass(frozen=True, slots=True)
class CashFlowBucket:
    start_on: date
    end_on: date
    operational_opening_balance: CashAmount
    operational_inflows: CashAmount
    operational_outflows: CashAmount
    operational_closing_balance: CashAmount
    scenario_opening_balance: CashAmount
    scenario_inflows: CashAmount
    scenario_outflows: CashAmount
    scenario_closing_balance: CashAmount
    liquidity_state: LiquidityState


@dataclass(frozen=True, slots=True)
class CashFlowProjection:
    """Immutable aggregate snapshot produced from one validated projection input."""

    id: UUID
    company_id: UUID
    as_of: date
    calculated_at: datetime
    horizon: CashFlowDateHorizon
    granularity: ProjectionGranularity
    opening_balance: CashAmount
    minimum_reserve: CashAmount
    scenario: CashFlowScenario
    source_items: tuple[CashFlowItem, ...]
    projected_items: tuple[CashFlowItem, ...]
    deferred_items: tuple[CashFlowItem, ...]
    source_gaps: tuple[CashFlowSourceGap, ...]
    buckets: tuple[CashFlowBucket, ...]
    summary: CashFlowSummary
    version: int

    def __post_init__(self) -> None:
        _uuid(self.id, "projection.id")
        _uuid(self.company_id, "projection.company_id")
        if not self.buckets:
            raise InvalidCashFlowError("projection must contain at least one bucket.")
        if self.buckets[0].start_on != self.horizon.start_on:
            raise InvalidCashFlowError("first bucket must start on the projection horizon.")
        if self.buckets[-1].end_on != self.horizon.end_on:
            raise InvalidCashFlowError("last bucket must end on the projection horizon.")
        for previous, current in zip(self.buckets, self.buckets[1:], strict=False):
            if current.start_on != previous.end_on + timedelta(days=1):
                raise InvalidCashFlowError("projection buckets must be contiguous.")
        if self.summary.company_id != self.company_id or self.summary.horizon != self.horizon:
            raise CashFlowScopeError("projection summary does not match the aggregate scope.")

    @property
    def liquidity_state(self) -> LiquidityState:
        return self.summary.liquidity_state


@dataclass(frozen=True, slots=True)
class CashFlowEngine:
    """Pure projection engine composed with an explicit business calendar."""

    calendar: BusinessCalendar
    policy: CashFlowPolicy = field(default_factory=CashFlowPolicy)

    def __post_init__(self) -> None:
        if not isinstance(self.calendar, BusinessCalendar):
            raise InvalidCashFlowError("calendar must be a BusinessCalendar.")
        if not isinstance(self.policy, CashFlowPolicy):
            raise InvalidCashFlowError("policy must be a CashFlowPolicy.")

    def project(self, request: CashFlowProjectionInput) -> CashFlowProjection:
        if not isinstance(request, CashFlowProjectionInput):
            raise InvalidCashFlowError("request must be a CashFlowProjectionInput.")
        candidates = self._apply_scenario(request)
        projected_items = self._ordered(
            item for item in candidates if request.horizon.contains(item.occurs_on)
        )
        deferred_items = self._ordered(
            item for item in candidates if not request.horizon.contains(item.occurs_on)
        )
        summary = self.policy.aggregate(
            company_id=request.company_id,
            horizon=request.horizon,
            opening_balance=request.opening_balance,
            minimum_reserve=request.minimum_reserve,
            items=projected_items,
            source_gaps=request.source_gaps,
        )
        buckets = self._buckets(request, projected_items)
        return CashFlowProjection(
            id=request.projection_id,
            company_id=request.company_id,
            as_of=request.as_of,
            calculated_at=request.calculated_at,
            horizon=request.horizon,
            granularity=request.granularity,
            opening_balance=request.opening_balance,
            minimum_reserve=request.minimum_reserve,
            scenario=request.scenario,
            source_items=request.items,
            projected_items=projected_items,
            deferred_items=deferred_items,
            source_gaps=request.source_gaps,
            buckets=buckets,
            summary=summary,
            version=request.version,
        )

    def _apply_scenario(self, request: CashFlowProjectionInput) -> tuple[CashFlowItem, ...]:
        result: list[CashFlowItem] = []
        for source in request.items:
            adjusted_on = source.occurs_on
            if source.certainty is not CashFlowCertainty.REALIZED:
                adjusted_on = self.calendar.adjust(
                    adjusted_on, request.scenario.business_day_convention
                )
            adjusted = replace(source, occurs_on=adjusted_on)
            result.append(adjusted)
            if (
                adjusted.certainty is CashFlowCertainty.COMMITTED
                and adjusted.origin is CashFlowOrigin.RECEIVABLE_INSTALLMENT
                and adjusted.direction is CashFlowDirection.INFLOW
                and request.scenario.receivable_delay_days > 0
            ):
                delayed_on = self.calendar.adjust(
                    source.occurs_on + timedelta(days=request.scenario.receivable_delay_days),
                    request.scenario.business_day_convention,
                )
                result.extend(
                    (
                        self._scenario_delta(adjusted, CashFlowDirection.OUTFLOW, adjusted_on),
                        self._scenario_delta(adjusted, CashFlowDirection.INFLOW, delayed_on),
                    )
                )
            if (
                adjusted.certainty is CashFlowCertainty.COMMITTED
                and adjusted.origin is CashFlowOrigin.PAYABLE_INSTALLMENT
                and adjusted.direction is CashFlowDirection.OUTFLOW
                and request.scenario.cost_variation_rate != 0
            ):
                delta = (adjusted.amount.amount * abs(request.scenario.cost_variation_rate)).quantize(
                    _CENT, rounding=ROUND_HALF_UP
                )
                if delta > 0:
                    direction = (
                        CashFlowDirection.OUTFLOW
                        if request.scenario.cost_variation_rate > 0
                        else CashFlowDirection.INFLOW
                    )
                    result.append(
                        self._scenario_delta(
                            adjusted,
                            direction,
                            adjusted_on,
                            amount=CashAmount(delta, adjusted.amount.currency),
                        )
                    )
        return tuple(result)

    @staticmethod
    def _scenario_delta(
        source: CashFlowItem,
        direction: CashFlowDirection,
        occurs_on: date,
        *,
        amount: CashAmount | None = None,
    ) -> CashFlowItem:
        return CashFlowItem(
            company_id=source.company_id,
            amount=amount or source.amount,
            occurs_on=occurs_on,
            direction=direction,
            category=source.category,
            certainty=CashFlowCertainty.SCENARIO,
            origin=CashFlowOrigin.MANUAL_SCENARIO,
            reference_id=None,
        )

    @staticmethod
    def _ordered(items: Iterable[CashFlowItem]) -> tuple[CashFlowItem, ...]:
        return tuple(
            sorted(
                items,
                key=lambda item: (
                    item.occurs_on,
                    item.certainty.value,
                    item.direction.value,
                    item.origin.value,
                    str(item.reference_id or ""),
                    item.amount.amount,
                ),
            )
        )

    def _buckets(
        self,
        request: CashFlowProjectionInput,
        items: tuple[CashFlowItem, ...],
    ) -> tuple[CashFlowBucket, ...]:
        operational_opening = request.opening_balance
        scenario_opening = request.opening_balance
        buckets: list[CashFlowBucket] = []
        for period in self._periods(request.horizon, request.granularity):
            period_items = tuple(item for item in items if period.contains(item.occurs_on))
            summary = self.policy.aggregate(
                company_id=request.company_id,
                horizon=period,
                opening_balance=operational_opening,
                minimum_reserve=request.minimum_reserve,
                items=period_items,
                source_gaps=request.source_gaps,
            )
            operational_inflows = CashAmount(
                summary.realized_inflows.amount + summary.committed_inflows.amount,
                summary.currency,
            )
            operational_outflows = CashAmount(
                summary.realized_outflows.amount + summary.committed_outflows.amount,
                summary.currency,
            )
            scenario_closing = CashAmount(
                scenario_opening.amount
                + operational_inflows.amount
                - operational_outflows.amount
                + summary.scenario_inflows.amount
                - summary.scenario_outflows.amount,
                summary.currency,
            )
            buckets.append(
                CashFlowBucket(
                    start_on=period.start_on,
                    end_on=period.end_on,
                    operational_opening_balance=operational_opening,
                    operational_inflows=operational_inflows,
                    operational_outflows=operational_outflows,
                    operational_closing_balance=summary.operational_closing_balance,
                    scenario_opening_balance=scenario_opening,
                    scenario_inflows=summary.scenario_inflows,
                    scenario_outflows=summary.scenario_outflows,
                    scenario_closing_balance=scenario_closing,
                    liquidity_state=summary.liquidity_state,
                )
            )
            operational_opening = summary.operational_closing_balance
            scenario_opening = scenario_closing
        return tuple(buckets)

    @staticmethod
    def _periods(
        horizon: CashFlowDateHorizon,
        granularity: ProjectionGranularity,
    ) -> tuple[CashFlowDateHorizon, ...]:
        periods: list[CashFlowDateHorizon] = []
        current = horizon.start_on
        while current <= horizon.end_on:
            if granularity is ProjectionGranularity.DAILY:
                period_end = current
            elif granularity is ProjectionGranularity.WEEKLY:
                period_end = current + timedelta(days=6 - current.weekday())
            else:
                first_next_month = (
                    date(current.year + 1, 1, 1)
                    if current.month == 12
                    else date(current.year, current.month + 1, 1)
                )
                period_end = first_next_month - timedelta(days=1)
            period_end = min(period_end, horizon.end_on)
            periods.append(CashFlowDateHorizon(current, period_end))
            current = period_end + timedelta(days=1)
        return tuple(periods)


__all__ = [
    "BusinessCalendar",
    "BusinessDayConvention",
    "CashFlowBucket",
    "CashFlowEngine",
    "CashFlowProjection",
    "CashFlowProjectionInput",
    "CashFlowScenario",
    "ProjectionGranularity",
]
