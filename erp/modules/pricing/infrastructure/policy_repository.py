"""Persistence adapter for M9 provisional costs and margin policies."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.pricing.domain import (
    LEGACY_OPENING,
    MinimumMarginPolicy,
    Money,
    Percentage,
    PricingPolicyStatus,
    StandardCostSeed,
)
from erp.modules.pricing.infrastructure.price_list_model import (
    MinimumMarginPolicyModel,
    StandardCostSeedModel,
)
from erp.platform.errors import ApplicationError


def _standard_cost(model: StandardCostSeedModel) -> StandardCostSeed:
    return StandardCostSeed(
        id=model.id,
        company_id=model.company_id,
        product_id=model.product_id,
        cost=Money.brl(model.cost_amount),
        source=model.source,
        version=model.version,
    )


def _minimum_margin(model: MinimumMarginPolicyModel) -> MinimumMarginPolicy:
    return MinimumMarginPolicy(
        id=model.id,
        company_id=model.company_id,
        code=model.code,
        name=model.name,
        minimum_margin=Percentage.ratio(model.minimum_margin),
        status=PricingPolicyStatus(model.status),
        version=model.version,
    )


class PricingPolicyRepository:
    """Company-scoped repository for sensitive M9 profitability inputs."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def upsert_standard_cost_seed(
        self, seed: StandardCostSeed, *, actor_id: UUID
    ) -> StandardCostSeed:
        self._validate_seed(seed, actor_id)
        existing = await self.standard_cost_seed(seed.product_id, for_update=True)
        if existing is None:
            model = StandardCostSeedModel(
                id=seed.id,
                company_id=self._company_id,
                product_id=seed.product_id,
                cost_amount=seed.cost.amount,
                currency=seed.cost.currency,
                source=LEGACY_OPENING,
                version=seed.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self._session.add(model)
            await self._flush_unique(code="STANDARD_COST_SEED_CONFLICT")
            return _standard_cost(model)
        result = await self._session.scalars(
            update(StandardCostSeedModel)
            .where(
                StandardCostSeedModel.company_id == self._company_id,
                StandardCostSeedModel.product_id == seed.product_id,
                StandardCostSeedModel.version == existing.version,
            )
            .values(
                cost_amount=seed.cost.amount,
                currency=seed.cost.currency,
                source=LEGACY_OPENING,
                updated_at=datetime.now(UTC),
                updated_by=actor_id,
                version=StandardCostSeedModel.version + 1,
            )
            .returning(StandardCostSeedModel)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        updated_model = result.one_or_none()
        if updated_model is None:
            raise ApplicationError(
                code="VERSION_CONFLICT",
                message="The standard cost seed was changed by another transaction.",
                status_code=409,
            )
        await self._session.flush()
        return _standard_cost(updated_model)

    async def create_minimum_margin_policy(
        self, policy: MinimumMarginPolicy, *, actor_id: UUID
    ) -> MinimumMarginPolicy:
        self._validate_policy(policy, actor_id)
        model = MinimumMarginPolicyModel(
            id=policy.id,
            company_id=self._company_id,
            code=policy.code,
            name=policy.name,
            minimum_margin=policy.minimum_margin.value,
            status=policy.status,
            version=policy.version,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(model)
        await self._flush_unique(code="MINIMUM_MARGIN_POLICY_CONFLICT")
        return _minimum_margin(model)

    async def standard_cost_seed(
        self, product_id: UUID, *, for_update: bool = False
    ) -> StandardCostSeed | None:
        statement = select(StandardCostSeedModel).where(
            StandardCostSeedModel.company_id == self._company_id,
            StandardCostSeedModel.product_id == product_id,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.scalars(
            statement.execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _standard_cost(model)

    async def active_minimum_margin_policy(self) -> MinimumMarginPolicy | None:
        result = await self._session.scalars(
            select(MinimumMarginPolicyModel)
            .where(
                MinimumMarginPolicyModel.company_id == self._company_id,
                MinimumMarginPolicyModel.status == PricingPolicyStatus.ACTIVE,
            )
            .order_by(MinimumMarginPolicyModel.created_at.desc(), MinimumMarginPolicyModel.id)
            .limit(1)
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _minimum_margin(model)

    async def _flush_unique(self, *, code: str) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code=code,
                    message="A pricing policy identifier is already in use.",
                    status_code=409,
                ) from error
            raise

    def _validate_seed(self, seed: StandardCostSeed, actor_id: UUID) -> None:
        if seed.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The standard cost seed is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    def _validate_policy(self, policy: MinimumMarginPolicy, actor_id: UUID) -> None:
        if policy.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The minimum-margin policy is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")


__all__ = ["PricingPolicyRepository"]
