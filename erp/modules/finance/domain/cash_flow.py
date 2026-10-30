"""Pure M12 cash-flow value objects and deterministic liquidity rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from erp.modules.finance.domain.exceptions import (
    CashFlowCurrencyMismatchError,
    CashFlowScopeError,
    HypotheticalCashFlowError,
    InvalidCashFlowError,
)

_CENT = Decimal("0.01")


def _uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidCashFlowError(f"{field} must be a non-zero UUID.")
    return value


def _text(value: str, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidCashFlowError(f"{field} must be text.")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise InvalidCashFlowError(f"{field} must contain between 1 and {maximum} characters.")
    return normalized


def _date(value: date, field: str) -> date:
    if type(value) is not date:
        raise InvalidCashFlowError(f"{field} must be a date.")
    return value


class CashFlowHorizonKind(StrEnum):
    SHORT_TERM = "SHORT_TERM"
    MEDIUM_TERM = "MEDIUM_TERM"
    LONG_TERM = "LONG_TERM"


class CashFlowCategory(StrEnum):
    OPERATING = "OPERATING"
    FINANCING = "FINANCING"
    INVESTING = "INVESTING"


class CashFlowDirection(StrEnum):
    INFLOW = "INFLOW"
    OUTFLOW = "OUTFLOW"


class CashFlowCertainty(StrEnum):
    REALIZED = "REALIZED"
    COMMITTED = "COMMITTED"
    SCENARIO = "SCENARIO"


class CashFlowOrigin(StrEnum):
    BANK_RECONCILIATION = "BANK_RECONCILIATION"
    PAYABLE_INSTALLMENT = "PAYABLE_INSTALLMENT"
    RECEIVABLE_INSTALLMENT = "RECEIVABLE_INSTALLMENT"
    MANUAL_SCENARIO = "MANUAL_SCENARIO"
    FISCAL_BILLING = "FISCAL_BILLING"


class CashFlowMissingSource(StrEnum):
    RECEIVABLES = "RECEIVABLES"
    BANK_POSITION = "BANK_POSITION"


class LiquidityState(StrEnum):
    HEALTHY = "HEALTHY"
    ATTENTION = "ATTENTION"
    CRITICAL = "CRITICAL"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True)
class CashAmount:
    """Exact ISO-currency monetary amount; floats are deliberately rejected."""

    amount: Decimal
    currency: str = "BRL"

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise InvalidCashFlowError("amount must be a finite Decimal.")
        try:
            normalized = self.amount.quantize(_CENT)
        except InvalidOperation as error:
            raise InvalidCashFlowError("amount uses unsupported monetary precision.") from error
        if normalized != self.amount:
            raise InvalidCashFlowError("amount must have at most two decimal places.")
        if not isinstance(self.currency, str):
            raise InvalidCashFlowError("currency must be text.")
        currency = self.currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise InvalidCashFlowError("currency must use an ISO 4217 alpha-3 code.")
        object.__setattr__(self, "amount", normalized)
        object.__setattr__(self, "currency", currency)

    def require_positive(self, field: str = "amount") -> CashAmount:
        if self.amount <= 0:
            raise InvalidCashFlowError(f"{field} must be positive.")
        return self


@dataclass(frozen=True, slots=True)
class CashFlowDateHorizon:
    start_on: date
    end_on: date

    def __post_init__(self) -> None:
        _date(self.start_on, "start_on")
        _date(self.end_on, "end_on")
        if self.end_on < self.start_on:
            raise InvalidCashFlowError("end_on cannot precede start_on.")

    @property
    def kind(self) -> CashFlowHorizonKind:
        duration = (self.end_on - self.start_on).days
        if duration <= 90:
            return CashFlowHorizonKind.SHORT_TERM
        if duration <= 365:
            return CashFlowHorizonKind.MEDIUM_TERM
        return CashFlowHorizonKind.LONG_TERM

    def contains(self, value: date) -> bool:
        return self.start_on <= _date(value, "value") <= self.end_on


@dataclass(frozen=True, slots=True)
class CashFlowItem:
    """Immutable, authoritative cash occurrence or explicitly isolated scenario."""

    company_id: UUID
    amount: CashAmount
    occurs_on: date
    direction: CashFlowDirection
    category: CashFlowCategory
    certainty: CashFlowCertainty
    origin: CashFlowOrigin
    reference_id: UUID | None

    def __post_init__(self) -> None:
        _uuid(self.company_id, "company_id")
        if not isinstance(self.amount, CashAmount):
            raise InvalidCashFlowError("amount must be a CashAmount.")
        self.amount.require_positive()
        _date(self.occurs_on, "occurs_on")
        if not isinstance(self.direction, CashFlowDirection):
            raise InvalidCashFlowError("direction must be a CashFlowDirection.")
        if not isinstance(self.category, CashFlowCategory):
            raise InvalidCashFlowError("category must be a CashFlowCategory.")
        if not isinstance(self.certainty, CashFlowCertainty):
            raise InvalidCashFlowError("certainty must be a CashFlowCertainty.")
        if not isinstance(self.origin, CashFlowOrigin):
            raise InvalidCashFlowError("origin must be a CashFlowOrigin.")
        if self.origin is CashFlowOrigin.FISCAL_BILLING:
            raise HypotheticalCashFlowError(
                "Fiscal billing is not cash authority; use an M13 receivable or an explicit source gap."
            )
        allowed_origins = {
            CashFlowCertainty.REALIZED: {CashFlowOrigin.BANK_RECONCILIATION},
            CashFlowCertainty.COMMITTED: {
                CashFlowOrigin.PAYABLE_INSTALLMENT,
                CashFlowOrigin.RECEIVABLE_INSTALLMENT,
            },
            CashFlowCertainty.SCENARIO: {CashFlowOrigin.MANUAL_SCENARIO},
        }
        if self.origin not in allowed_origins[self.certainty]:
            raise InvalidCashFlowError("origin is not authoritative for the selected certainty.")
        if self.origin is CashFlowOrigin.MANUAL_SCENARIO:
            if self.reference_id is not None:
                raise InvalidCashFlowError("manual scenarios cannot impersonate an authoritative reference.")
        elif self.reference_id is None:
            raise InvalidCashFlowError("authoritative cash-flow items require reference_id.")
        else:
            _uuid(self.reference_id, "reference_id")


@dataclass(frozen=True, slots=True)
class CashFlowSourceGap:
    """Explicit missing authority; it must never be converted into hypothetical cash."""

    company_id: UUID
    source: CashFlowMissingSource
    horizon: CashFlowDateHorizon
    reason: str

    def __post_init__(self) -> None:
        _uuid(self.company_id, "company_id")
        if not isinstance(self.source, CashFlowMissingSource):
            raise InvalidCashFlowError("source must be a CashFlowMissingSource.")
        if not isinstance(self.horizon, CashFlowDateHorizon):
            raise InvalidCashFlowError("horizon must be a CashFlowDateHorizon.")
        object.__setattr__(self, "reason", _text(self.reason, "reason", maximum=500))


@dataclass(frozen=True, slots=True)
class CashFlowSummary:
    company_id: UUID
    horizon: CashFlowDateHorizon
    currency: str
    opening_balance: CashAmount
    realized_inflows: CashAmount
    realized_outflows: CashAmount
    committed_inflows: CashAmount
    committed_outflows: CashAmount
    scenario_inflows: CashAmount
    scenario_outflows: CashAmount
    operational_closing_balance: CashAmount
    scenario_closing_balance: CashAmount
    liquidity_state: LiquidityState
    source_gaps: tuple[CashFlowSourceGap, ...]


@dataclass(frozen=True, slots=True)
class CashFlowPolicy:
    """Deterministic aggregation; scenarios never alter operational liquidity."""

    def aggregate(
        self,
        *,
        company_id: UUID,
        horizon: CashFlowDateHorizon,
        opening_balance: CashAmount,
        minimum_reserve: CashAmount,
        items: tuple[CashFlowItem, ...],
        source_gaps: tuple[CashFlowSourceGap, ...] = (),
    ) -> CashFlowSummary:
        _uuid(company_id, "company_id")
        if not isinstance(horizon, CashFlowDateHorizon):
            raise InvalidCashFlowError("horizon must be a CashFlowDateHorizon.")
        if not isinstance(opening_balance, CashAmount):
            raise InvalidCashFlowError("opening_balance must be a CashAmount.")
        if not isinstance(minimum_reserve, CashAmount):
            raise InvalidCashFlowError("minimum_reserve must be a CashAmount.")
        if opening_balance.currency != minimum_reserve.currency:
            raise CashFlowCurrencyMismatchError("opening balance and reserve must use one currency.")
        if minimum_reserve.amount < 0:
            raise InvalidCashFlowError("minimum_reserve cannot be negative.")

        totals = {
            (certainty, direction): Decimal("0.00")
            for certainty in CashFlowCertainty
            for direction in CashFlowDirection
        }
        for item in items:
            if not isinstance(item, CashFlowItem):
                raise InvalidCashFlowError("items must contain CashFlowItem values.")
            if item.company_id != company_id:
                raise CashFlowScopeError("cash-flow item belongs to another company.")
            if item.amount.currency != opening_balance.currency:
                raise CashFlowCurrencyMismatchError("cash-flow item uses another currency.")
            if not horizon.contains(item.occurs_on):
                raise InvalidCashFlowError("cash-flow item is outside the requested horizon.")
            totals[(item.certainty, item.direction)] += item.amount.amount

        for gap in source_gaps:
            if not isinstance(gap, CashFlowSourceGap):
                raise InvalidCashFlowError("source_gaps must contain CashFlowSourceGap values.")
            if gap.company_id != company_id:
                raise CashFlowScopeError("source gap belongs to another company.")
            if gap.horizon.start_on > horizon.start_on or gap.horizon.end_on < horizon.end_on:
                raise InvalidCashFlowError("source gap must cover the requested horizon.")

        currency = opening_balance.currency

        def money(certainty: CashFlowCertainty, direction: CashFlowDirection) -> CashAmount:
            return CashAmount(totals[(certainty, direction)], currency)

        realized_inflows = money(CashFlowCertainty.REALIZED, CashFlowDirection.INFLOW)
        realized_outflows = money(CashFlowCertainty.REALIZED, CashFlowDirection.OUTFLOW)
        committed_inflows = money(CashFlowCertainty.COMMITTED, CashFlowDirection.INFLOW)
        committed_outflows = money(CashFlowCertainty.COMMITTED, CashFlowDirection.OUTFLOW)
        scenario_inflows = money(CashFlowCertainty.SCENARIO, CashFlowDirection.INFLOW)
        scenario_outflows = money(CashFlowCertainty.SCENARIO, CashFlowDirection.OUTFLOW)
        operational_amount = (
            opening_balance.amount
            + realized_inflows.amount
            - realized_outflows.amount
            + committed_inflows.amount
            - committed_outflows.amount
        )
        scenario_amount = operational_amount + scenario_inflows.amount - scenario_outflows.amount
        operational_closing = CashAmount(operational_amount, currency)

        if source_gaps:
            liquidity_state = LiquidityState.INCOMPLETE
        elif operational_amount < 0:
            liquidity_state = LiquidityState.CRITICAL
        elif operational_amount < minimum_reserve.amount:
            liquidity_state = LiquidityState.ATTENTION
        else:
            liquidity_state = LiquidityState.HEALTHY

        return CashFlowSummary(
            company_id=company_id,
            horizon=horizon,
            currency=currency,
            opening_balance=opening_balance,
            realized_inflows=realized_inflows,
            realized_outflows=realized_outflows,
            committed_inflows=committed_inflows,
            committed_outflows=committed_outflows,
            scenario_inflows=scenario_inflows,
            scenario_outflows=scenario_outflows,
            operational_closing_balance=operational_closing,
            scenario_closing_balance=CashAmount(scenario_amount, currency),
            liquidity_state=liquidity_state,
            source_gaps=source_gaps,
        )


__all__ = [
    "CashAmount",
    "CashFlowCategory",
    "CashFlowCertainty",
    "CashFlowDateHorizon",
    "CashFlowDirection",
    "CashFlowHorizonKind",
    "CashFlowItem",
    "CashFlowMissingSource",
    "CashFlowOrigin",
    "CashFlowPolicy",
    "CashFlowSourceGap",
    "CashFlowSummary",
    "LiquidityState",
]
