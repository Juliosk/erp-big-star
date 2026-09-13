"""Pricing resolution use case for M9."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.pricing.application.permissions import (
    PRICING_MARGIN_VIEW_SENSITIVE,
    PRICING_SIMULATE,
    PricingAuthorization,
)
from erp.modules.pricing.contracts import PricingResolution, PricingResolutionRequest
from erp.modules.pricing.domain import (
    MinimumMarginPolicy,
    Money,
    Percentage,
    PriceListItem,
    StandardCostSeed,
    ensure_minimum_margin,
)
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class PricingCandidate:
    price_list_id: UUID
    price_list_version_id: UUID
    source: str
    item: PriceListItem


@dataclass(frozen=True, slots=True)
class PricingSnapshotDraft:
    company_id: UUID
    product_id: UUID
    price_list_id: UUID
    price_list_version_id: UUID
    cost: StandardCostSeed
    unit_price: Money
    minimum_price: Money | None
    target_margin: Percentage | None
    minimum_margin: Percentage | None
    effective_margin: Percentage
    source: str


class PricingResolutionStore(Protocol):
    async def find_candidate(
        self,
        request: PricingResolutionRequest,
    ) -> PricingCandidate | None: ...

    async def standard_cost_seed(
        self, company_id: UUID, product_id: UUID
    ) -> StandardCostSeed | None: ...

    async def active_minimum_margin_policy(
        self, company_id: UUID
    ) -> MinimumMarginPolicy | None: ...

    async def create_pricing_snapshot(
        self, draft: PricingSnapshotDraft, actor_id: UUID
    ) -> UUID: ...


class PricingResolutionService:
    """Resolve sell price and freeze the decision in pricing_snapshot."""

    def __init__(self, store: PricingResolutionStore, authorization: PricingAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def resolve(
        self, context: SecurityContext, request: PricingResolutionRequest
    ) -> PricingResolution:
        await self._authorization.require(context, request.company_id, PRICING_SIMULATE)
        if request.quantity <= 0:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid pricing request.",
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
                message="The resolved price does not satisfy profitability policy.",
                status_code=422,
                details=[ErrorDetail(message=str(error))],
            ) from error
        minimum_margin = None if policy is None else policy.minimum_margin
        snapshot_id = await self._store.create_pricing_snapshot(
            PricingSnapshotDraft(
                company_id=request.company_id,
                product_id=request.product_id,
                price_list_id=candidate.price_list_id,
                price_list_version_id=candidate.price_list_version_id,
                cost=cost,
                unit_price=candidate.item.price,
                minimum_price=candidate.item.minimum_price,
                target_margin=candidate.item.target_margin,
                minimum_margin=minimum_margin,
                effective_margin=effective_margin,
                source=candidate.source,
            ),
            context.principal.user_id,
        )
        can_view_margin = PRICING_MARGIN_VIEW_SENSITIVE in context.permissions
        return PricingResolution(
            pricing_snapshot_id=snapshot_id,
            company_id=request.company_id,
            product_id=request.product_id,
            quantity=request.quantity,
            currency=candidate.item.price.currency,
            unit_price=candidate.item.price.amount,
            total_price=candidate.item.price.amount * request.quantity,
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


__all__ = [
    "PricingCandidate",
    "PricingResolutionService",
    "PricingResolutionStore",
    "PricingSnapshotDraft",
]
