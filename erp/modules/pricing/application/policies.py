"""Application services for provisional costs and profitability guardrails."""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.pricing.application.permissions import PRICING_PRICE_CREATE, PricingAuthorization
from erp.modules.pricing.domain import (
    MinimumMarginPolicy,
    Money,
    Percentage,
    StandardCostSeed,
    ensure_minimum_margin,
)
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class UpsertStandardCostSeed:
    company_id: UUID
    product_id: UUID
    cost_amount: Decimal


@dataclass(frozen=True, slots=True)
class CreateMinimumMarginPolicy:
    company_id: UUID
    code: str
    name: str
    minimum_margin: Decimal


class PricingPolicyStore(Protocol):
    async def upsert_standard_cost_seed(
        self, seed: StandardCostSeed, actor_id: UUID
    ) -> StandardCostSeed: ...

    async def create_minimum_margin_policy(
        self, policy: MinimumMarginPolicy, actor_id: UUID
    ) -> MinimumMarginPolicy: ...

    async def standard_cost_seed(self, company_id: UUID, product_id: UUID) -> StandardCostSeed | None: ...

    async def active_minimum_margin_policy(
        self, company_id: UUID
    ) -> MinimumMarginPolicy | None: ...


class PricingPolicyService:
    """Maintain provisional pricing guardrails until dedicated M8 costing is active."""

    def __init__(self, store: PricingPolicyStore, authorization: PricingAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def upsert_standard_cost_seed(
        self, context: SecurityContext, command: UpsertStandardCostSeed
    ) -> StandardCostSeed:
        await self._authorization.require(
            context, command.company_id, PRICING_PRICE_CREATE, write=True
        )
        seed = self._build(
            lambda: StandardCostSeed.create(
                company_id=command.company_id,
                product_id=command.product_id,
                cost=Money.brl(command.cost_amount),
            )
        )
        return await self._store.upsert_standard_cost_seed(seed, context.principal.user_id)

    async def create_minimum_margin_policy(
        self, context: SecurityContext, command: CreateMinimumMarginPolicy
    ) -> MinimumMarginPolicy:
        await self._authorization.require(
            context, command.company_id, PRICING_PRICE_CREATE, write=True
        )
        policy = self._build(
            lambda: MinimumMarginPolicy.create(
                company_id=command.company_id,
                code=command.code,
                name=command.name,
                minimum_margin=Percentage.ratio(command.minimum_margin),
            )
        )
        return await self._store.create_minimum_margin_policy(
            policy, context.principal.user_id
        )

    async def validate_profitability(
        self,
        context: SecurityContext,
        *,
        company_id: UUID,
        product_id: UUID,
        price: Money,
    ) -> Percentage:
        await self._authorization.require(context, company_id, PRICING_PRICE_CREATE, write=True)
        cost = await self._store.standard_cost_seed(company_id, product_id)
        if cost is None:
            raise ApplicationError(
                code="STANDARD_COST_NOT_FOUND",
                message="No provisional standard cost is available for this product.",
                status_code=422,
            )
        policy = await self._store.active_minimum_margin_policy(company_id)
        try:
            return ensure_minimum_margin(price=price, cost=cost, policy=policy)
        except ValueError as error:
            raise ApplicationError(
                code="MINIMUM_MARGIN_VIOLATION",
                message="The proposed price does not satisfy profitability policy.",
                status_code=422,
                details=[ErrorDetail(message=str(error))],
            ) from error

    @staticmethod
    def _build[T](factory: Callable[[], T]) -> T:
        try:
            return factory()
        except ValueError as error:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid pricing policy data.",
                status_code=422,
                details=[ErrorDetail(message=str(error))],
            ) from error


__all__ = [
    "CreateMinimumMarginPolicy",
    "PricingPolicyService",
    "PricingPolicyStore",
    "UpsertStandardCostSeed",
]
