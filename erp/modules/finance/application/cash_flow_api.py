"""Application boundary for versioned Cash Flow queries and simulations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.finance.application.cash_flow import ComposeCashFlowProjection
from erp.modules.finance.application.permissions import (
    FINANCE_CASH_FLOW_PROJECT,
    FINANCE_CASH_FLOW_READ,
    FINANCE_CASH_FLOW_SCENARIO,
    FinanceAuthorization,
)
from erp.modules.finance.domain import (
    BusinessDayConvention,
    CashFlowCategory,
    CashFlowCertainty,
    CashFlowDirection,
    CashFlowHorizonKind,
    CashFlowProjection,
    CashFlowScenario,
)


@dataclass(frozen=True, slots=True)
class CashFlowCategoryTotals:
    """Exact totals for the category selection carried by an API query."""

    currency: str
    realized_inflows: Decimal
    realized_outflows: Decimal
    committed_inflows: Decimal
    committed_outflows: Decimal
    scenario_inflows: Decimal
    scenario_outflows: Decimal


@dataclass(frozen=True, slots=True)
class CashFlowProjectionView:
    projection: CashFlowProjection
    selected_categories: tuple[CashFlowCategory, ...]
    category_totals: CashFlowCategoryTotals


@dataclass(frozen=True, slots=True)
class CashFlowProjectionPage:
    items: tuple[CashFlowProjection, ...]
    page: int
    page_size: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class CashFlowMutationResult:
    projection: CashFlowProjection
    idempotency_replayed: bool
    persisted: bool
    base_version: int | None


@dataclass(frozen=True, slots=True)
class RefreshCashFlowProjection:
    company_id: UUID
    projection_id: UUID
    expected_version: int
    idempotency_key: str
    calculated_at: datetime


@dataclass(frozen=True, slots=True)
class SimulateCashFlowScenario:
    company_id: UUID
    projection_id: UUID
    expected_version: int
    scenario_id: UUID
    name: str
    receivable_delay_days: int
    cost_variation_rate: Decimal
    business_day_convention: BusinessDayConvention
    idempotency_key: str
    calculated_at: datetime

    def scenario(self) -> CashFlowScenario:
        return CashFlowScenario(
            id=self.scenario_id,
            name=self.name,
            receivable_delay_days=self.receivable_delay_days,
            cost_variation_rate=self.cost_variation_rate,
            business_day_convention=self.business_day_convention,
        )


class CashFlowOperations(Protocol):
    async def list_latest(
        self,
        company_id: UUID,
        *,
        horizon: CashFlowHorizonKind,
        page: int,
        page_size: int,
    ) -> CashFlowProjectionPage: ...

    async def get(
        self, company_id: UUID, projection_id: UUID
    ) -> CashFlowProjection | None: ...

    async def project(
        self,
        command: ComposeCashFlowProjection,
        *,
        actor_id: UUID,
        idempotency_key: str,
    ) -> CashFlowMutationResult: ...

    async def refresh(
        self,
        command: RefreshCashFlowProjection,
        *,
        actor_id: UUID,
    ) -> CashFlowMutationResult: ...

    async def simulate(
        self,
        command: SimulateCashFlowScenario,
        *,
        actor_id: UUID,
    ) -> CashFlowMutationResult: ...


class CashFlowApplicationService:
    """Authorize one company scope and delegate I/O to an injected port."""

    def __init__(
        self,
        operations: CashFlowOperations,
        authorization: FinanceAuthorization,
    ) -> None:
        self._operations = operations
        self._authorization = authorization

    async def list_horizon(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        horizon: CashFlowHorizonKind,
        categories: tuple[CashFlowCategory, ...],
        page: int,
        page_size: int,
    ) -> tuple[tuple[CashFlowProjectionView, ...], int, int, bool]:
        await self._authorization.require(
            context, company_id, FINANCE_CASH_FLOW_READ, write=False
        )
        result = await self._operations.list_latest(
            company_id, horizon=horizon, page=page, page_size=page_size
        )
        return (
            tuple(_view(item, categories) for item in result.items),
            result.page,
            result.page_size,
            result.has_more,
        )

    async def get(
        self,
        context: SecurityContext,
        company_id: UUID,
        projection_id: UUID,
        *,
        categories: tuple[CashFlowCategory, ...],
    ) -> CashFlowProjectionView:
        await self._authorization.require(
            context, company_id, FINANCE_CASH_FLOW_READ, write=False
        )
        projection = await self._operations.get(company_id, projection_id)
        if projection is None:
            from erp.platform.errors import ApplicationError

            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Cash Flow projection not found in the selected company.",
                status_code=404,
            )
        return _view(projection, categories)

    async def project(
        self,
        context: SecurityContext,
        command: ComposeCashFlowProjection,
        *,
        idempotency_key: str,
    ) -> CashFlowMutationResult:
        await self._authorization.require(
            context, command.company_id, FINANCE_CASH_FLOW_PROJECT, write=True
        )
        return await self._operations.project(
            command,
            actor_id=context.principal.user_id,
            idempotency_key=idempotency_key,
        )

    async def refresh(
        self,
        context: SecurityContext,
        command: RefreshCashFlowProjection,
    ) -> CashFlowMutationResult:
        await self._authorization.require(
            context, command.company_id, FINANCE_CASH_FLOW_PROJECT, write=True
        )
        return await self._operations.refresh(
            command, actor_id=context.principal.user_id
        )

    async def simulate(
        self,
        context: SecurityContext,
        command: SimulateCashFlowScenario,
    ) -> CashFlowMutationResult:
        await self._authorization.require(
            context, command.company_id, FINANCE_CASH_FLOW_SCENARIO, write=False
        )
        return await self._operations.simulate(
            command, actor_id=context.principal.user_id
        )


def utc_now() -> datetime:
    """Single injectable-looking clock seam kept at the HTTP/application edge."""

    return datetime.now(UTC)


def _view(
    projection: CashFlowProjection,
    categories: tuple[CashFlowCategory, ...],
) -> CashFlowProjectionView:
    selected = categories or tuple(CashFlowCategory)
    totals = {
        (certainty, direction): Decimal("0.00")
        for certainty in CashFlowCertainty
        for direction in CashFlowDirection
    }
    for item in projection.projected_items:
        if item.category in selected:
            totals[(item.certainty, item.direction)] += item.amount.amount
    return CashFlowProjectionView(
        projection=projection,
        selected_categories=selected,
        category_totals=CashFlowCategoryTotals(
            currency=projection.summary.currency,
            realized_inflows=totals[(CashFlowCertainty.REALIZED, CashFlowDirection.INFLOW)],
            realized_outflows=totals[(CashFlowCertainty.REALIZED, CashFlowDirection.OUTFLOW)],
            committed_inflows=totals[(CashFlowCertainty.COMMITTED, CashFlowDirection.INFLOW)],
            committed_outflows=totals[(CashFlowCertainty.COMMITTED, CashFlowDirection.OUTFLOW)],
            scenario_inflows=totals[(CashFlowCertainty.SCENARIO, CashFlowDirection.INFLOW)],
            scenario_outflows=totals[(CashFlowCertainty.SCENARIO, CashFlowDirection.OUTFLOW)],
        ),
    )


__all__ = [
    "CashFlowApplicationService",
    "CashFlowCategoryTotals",
    "CashFlowMutationResult",
    "CashFlowOperations",
    "CashFlowProjectionPage",
    "CashFlowProjectionView",
    "RefreshCashFlowProjection",
    "SimulateCashFlowScenario",
    "utc_now",
]
