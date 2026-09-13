"""Real-time pricing simulation without durable snapshots."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.pricing.application.permissions import (
    PRICING_MARGIN_VIEW_SENSITIVE,
    PRICING_SIMULATE,
    PricingAuthorization,
)
from erp.modules.pricing.application.resolution import PricingResolutionStore
from erp.modules.pricing.contracts import PricingResolutionRequest
from erp.modules.pricing.domain import Money, ensure_minimum_margin
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class PricingSimulation:
    request: PricingResolutionRequest
    currency: str
    unit_price: Decimal
    total_price: Decimal
    minimum_price: Decimal | None
    price_list_id: UUID
    price_list_version_id: UUID
    minimum_margin: Decimal | None
    effective_margin: Decimal | None
    source: str
    persisted: bool = False


class PricingSimulationService:
    """Project a pricing decision without writing pricing_snapshot."""

    def __init__(self, store: PricingResolutionStore, authorization: PricingAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def simulate(
        self, context: SecurityContext, request: PricingResolutionRequest
    ) -> PricingSimulation:
        await self._authorization.require(context, request.company_id, PRICING_SIMULATE)
        if request.quantity <= 0:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid pricing simulation.",
                status_code=422,
                details=[ErrorDetail(message="quantity must be greater than zero.")],
            )
        candidate = await self._store.find_candidate(request)
        if candidate is None:
            raise ApplicationError(
                code="PRICE_NOT_FOUND",
                message="No active price was found for the selected product.",
                status_code=404,
            )
        cost = await self._store.standard_cost_seed(request.company_id, request.product_id)
        if cost is None:
            raise ApplicationError(
                code="STANDARD_COST_NOT_FOUND",
                message="No provisional standard cost is available for this product.",
                status_code=422,
            )
        policy = await self._store.active_minimum_margin_policy(request.company_id)
        try:
            effective_margin = ensure_minimum_margin(
                price=candidate.item.price, cost=cost, policy=policy
            )
        except ValueError as error:
            raise ApplicationError(
                code="MINIMUM_MARGIN_VIOLATION",
                message="The simulated price does not satisfy profitability policy.",
                status_code=422,
                details=[ErrorDetail(message=str(error))],
            ) from error
        minimum_margin = None if policy is None else policy.minimum_margin
        can_view_margin = PRICING_MARGIN_VIEW_SENSITIVE in context.permissions
        unit_price = candidate.item.price.amount
        return PricingSimulation(
            request=request,
            currency=candidate.item.price.currency,
            unit_price=unit_price,
            total_price=unit_price * request.quantity,
            minimum_price=(
                None
                if candidate.item.minimum_price is None
                else candidate.item.minimum_price.amount
            ),
            price_list_id=candidate.price_list_id,
            price_list_version_id=candidate.price_list_version_id,
            minimum_margin=None if minimum_margin is None else minimum_margin.value,
            effective_margin=effective_margin.value if can_view_margin else None,
            source=candidate.source,
        )

    async def simulate_override(
        self,
        context: SecurityContext,
        request: PricingResolutionRequest,
        *,
        proposed_unit_price: Decimal,
    ) -> PricingSimulation:
        await self._authorization.require(context, request.company_id, PRICING_SIMULATE)
        if request.quantity <= 0 or proposed_unit_price <= 0:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid pricing simulation.",
                status_code=422,
                details=[
                    ErrorDetail(
                        message="quantity and proposed_unit_price must be greater than zero."
                    )
                ],
            )
        candidate = await self._store.find_candidate(request)
        if candidate is None:
            raise ApplicationError(
                code="PRICE_NOT_FOUND",
                message="No active price was found for the selected product.",
                status_code=404,
            )
        cost = await self._store.standard_cost_seed(request.company_id, request.product_id)
        if cost is None:
            raise ApplicationError(
                code="STANDARD_COST_NOT_FOUND",
                message="No provisional standard cost is available for this product.",
                status_code=422,
            )
        policy = await self._store.active_minimum_margin_policy(request.company_id)
        proposed = Money.brl(proposed_unit_price)
        try:
            effective_margin = ensure_minimum_margin(price=proposed, cost=cost, policy=policy)
        except ValueError as error:
            raise ApplicationError(
                code="MINIMUM_MARGIN_VIOLATION",
                message="The simulated price does not satisfy profitability policy.",
                status_code=422,
                details=[ErrorDetail(message=str(error))],
            ) from error
        minimum_margin = None if policy is None else policy.minimum_margin
        can_view_margin = PRICING_MARGIN_VIEW_SENSITIVE in context.permissions
        return PricingSimulation(
            request=request,
            currency=proposed.currency,
            unit_price=proposed.amount,
            total_price=proposed.amount * request.quantity,
            minimum_price=(
                None
                if candidate.item.minimum_price is None
                else candidate.item.minimum_price.amount
            ),
            price_list_id=candidate.price_list_id,
            price_list_version_id=candidate.price_list_version_id,
            minimum_margin=None if minimum_margin is None else minimum_margin.value,
            effective_margin=effective_margin.value if can_view_margin else None,
            source="SIMULATION_OVERRIDE",
        )


__all__ = ["PricingSimulation", "PricingSimulationService"]
