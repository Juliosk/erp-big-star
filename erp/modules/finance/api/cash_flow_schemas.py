"""HTTP schemas for versioned Cash Flow projections and stateless scenarios."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.finance.application.cash_flow_api import (
    CashFlowMutationResult,
    CashFlowProjectionView,
)
from erp.modules.finance.domain import CashAmount, CashFlowCategory, CashFlowProjection


class CashFlowScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: str = Field(min_length=1, max_length=120)
    receivable_delay_days: int = Field(default=0, ge=0, le=365)
    cost_variation_rate: Decimal = Field(default=Decimal("0.0000"), ge=-1, le=10)
    business_day_convention: str = "FOLLOWING"


class CreateCashFlowProjectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    projection_id: UUID
    as_of: date
    horizon_end: date
    granularity: str
    minimum_reserve: Decimal = Field(ge=0, decimal_places=2)
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    scenario: CashFlowScenarioRequest


class SimulateCashFlowScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    projection_id: UUID
    scenario: CashFlowScenarioRequest


class CashAmountResponse(BaseModel):
    amount: Decimal
    currency: str


class CashFlowItemResponse(BaseModel):
    amount: CashAmountResponse
    occurs_on: date
    direction: str
    category: str
    certainty: str
    origin: str
    reference_id: UUID | None


class CashFlowGapResponse(BaseModel):
    source: str
    start_on: date
    end_on: date
    reason: str


class CashFlowBucketResponse(BaseModel):
    start_on: date
    end_on: date
    operational_opening_balance: CashAmountResponse
    operational_inflows: CashAmountResponse
    operational_outflows: CashAmountResponse
    operational_closing_balance: CashAmountResponse
    scenario_opening_balance: CashAmountResponse
    scenario_inflows: CashAmountResponse
    scenario_outflows: CashAmountResponse
    scenario_closing_balance: CashAmountResponse
    liquidity_state: str


class CashFlowTotalsResponse(BaseModel):
    currency: str
    realized_inflows: Decimal
    realized_outflows: Decimal
    committed_inflows: Decimal
    committed_outflows: Decimal
    scenario_inflows: Decimal
    scenario_outflows: Decimal


class CashFlowSummaryResponse(CashFlowTotalsResponse):
    opening_balance: Decimal
    operational_closing_balance: Decimal
    scenario_closing_balance: Decimal
    liquidity_state: str


class CashFlowScenarioResponse(BaseModel):
    id: UUID
    name: str
    receivable_delay_days: int
    cost_variation_rate: Decimal
    business_day_convention: str


class CashFlowProjectionResponse(BaseModel):
    id: UUID
    company_id: UUID
    version: int
    as_of: date
    calculated_at: datetime
    horizon_start: date
    horizon_end: date
    horizon_kind: str
    granularity: str
    opening_balance: CashAmountResponse
    minimum_reserve: CashAmountResponse
    scenario: CashFlowScenarioResponse
    summary: CashFlowSummaryResponse
    selected_categories: list[str]
    category_totals: CashFlowTotalsResponse
    source_gaps: list[CashFlowGapResponse]
    items: list[CashFlowItemResponse]
    buckets: list[CashFlowBucketResponse]

    @classmethod
    def from_view(cls, value: CashFlowProjectionView) -> CashFlowProjectionResponse:
        return cls._from_projection(
            value.projection,
            selected_categories=value.selected_categories,
            category_totals=CashFlowTotalsResponse(
                currency=value.category_totals.currency,
                realized_inflows=value.category_totals.realized_inflows,
                realized_outflows=value.category_totals.realized_outflows,
                committed_inflows=value.category_totals.committed_inflows,
                committed_outflows=value.category_totals.committed_outflows,
                scenario_inflows=value.category_totals.scenario_inflows,
                scenario_outflows=value.category_totals.scenario_outflows,
            ),
        )

    @classmethod
    def from_projection(cls, value: CashFlowProjection) -> CashFlowProjectionResponse:
        categories = tuple(CashFlowCategory)
        totals = value.summary
        return cls._from_projection(
            value,
            selected_categories=categories,
            category_totals=CashFlowTotalsResponse(
                currency=totals.currency,
                realized_inflows=totals.realized_inflows.amount,
                realized_outflows=totals.realized_outflows.amount,
                committed_inflows=totals.committed_inflows.amount,
                committed_outflows=totals.committed_outflows.amount,
                scenario_inflows=totals.scenario_inflows.amount,
                scenario_outflows=totals.scenario_outflows.amount,
            ),
        )

    @classmethod
    def _from_projection(
        cls,
        value: CashFlowProjection,
        *,
        selected_categories: tuple[CashFlowCategory, ...],
        category_totals: CashFlowTotalsResponse,
    ) -> CashFlowProjectionResponse:
        summary = value.summary
        selected = set(selected_categories)
        return cls(
            id=value.id,
            company_id=value.company_id,
            version=value.version,
            as_of=value.as_of,
            calculated_at=value.calculated_at,
            horizon_start=value.horizon.start_on,
            horizon_end=value.horizon.end_on,
            horizon_kind=value.horizon.kind.value,
            granularity=value.granularity.value,
            opening_balance=_amount(value.opening_balance),
            minimum_reserve=_amount(value.minimum_reserve),
            scenario=CashFlowScenarioResponse(
                id=value.scenario.id,
                name=value.scenario.name,
                receivable_delay_days=value.scenario.receivable_delay_days,
                cost_variation_rate=value.scenario.cost_variation_rate,
                business_day_convention=value.scenario.business_day_convention.value,
            ),
            summary=CashFlowSummaryResponse(
                currency=summary.currency,
                opening_balance=summary.opening_balance.amount,
                realized_inflows=summary.realized_inflows.amount,
                realized_outflows=summary.realized_outflows.amount,
                committed_inflows=summary.committed_inflows.amount,
                committed_outflows=summary.committed_outflows.amount,
                scenario_inflows=summary.scenario_inflows.amount,
                scenario_outflows=summary.scenario_outflows.amount,
                operational_closing_balance=summary.operational_closing_balance.amount,
                scenario_closing_balance=summary.scenario_closing_balance.amount,
                liquidity_state=summary.liquidity_state.value,
            ),
            selected_categories=[item.value for item in selected_categories],
            category_totals=category_totals,
            source_gaps=[
                CashFlowGapResponse(
                    source=gap.source.value,
                    start_on=gap.horizon.start_on,
                    end_on=gap.horizon.end_on,
                    reason=gap.reason,
                )
                for gap in value.source_gaps
            ],
            items=[
                CashFlowItemResponse(
                    amount=_amount(item.amount),
                    occurs_on=item.occurs_on,
                    direction=item.direction.value,
                    category=item.category.value,
                    certainty=item.certainty.value,
                    origin=item.origin.value,
                    reference_id=item.reference_id,
                )
                for item in value.projected_items
                if item.category in selected
            ],
            buckets=[
                CashFlowBucketResponse(
                    start_on=bucket.start_on,
                    end_on=bucket.end_on,
                    operational_opening_balance=_amount(bucket.operational_opening_balance),
                    operational_inflows=_amount(bucket.operational_inflows),
                    operational_outflows=_amount(bucket.operational_outflows),
                    operational_closing_balance=_amount(bucket.operational_closing_balance),
                    scenario_opening_balance=_amount(bucket.scenario_opening_balance),
                    scenario_inflows=_amount(bucket.scenario_inflows),
                    scenario_outflows=_amount(bucket.scenario_outflows),
                    scenario_closing_balance=_amount(bucket.scenario_closing_balance),
                    liquidity_state=bucket.liquidity_state.value,
                )
                for bucket in value.buckets
            ],
        )


class CashFlowProjectionPageResponse(BaseModel):
    data: list[CashFlowProjectionResponse]
    page: int
    page_size: int
    has_more: bool


class CashFlowMutationResponse(BaseModel):
    projection: CashFlowProjectionResponse
    persisted: bool
    base_version: int | None
    idempotency_replayed: bool

    @classmethod
    def from_application(cls, value: CashFlowMutationResult) -> CashFlowMutationResponse:
        return cls(
            projection=CashFlowProjectionResponse.from_projection(value.projection),
            persisted=value.persisted,
            base_version=value.base_version,
            idempotency_replayed=value.idempotency_replayed,
        )


def _amount(value: CashAmount) -> CashAmountResponse:
    return CashAmountResponse(amount=value.amount, currency=value.currency)


__all__ = [
    "CashFlowMutationResponse",
    "CashFlowProjectionPageResponse",
    "CashFlowProjectionResponse",
    "CreateCashFlowProjectionRequest",
    "SimulateCashFlowScenarioRequest",
]
