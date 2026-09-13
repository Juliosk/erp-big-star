"""Session-owning adapter for M9 pricing policies."""

from uuid import UUID

from erp.modules.pricing.application.policies import PricingPolicyStore
from erp.modules.pricing.domain import MinimumMarginPolicy, StandardCostSeed
from erp.modules.pricing.infrastructure.policy_repository import PricingPolicyRepository
from erp.platform.database import Database


class PostgresPricingPolicies(PricingPolicyStore):
    """Expose company-scoped policy persistence behind application ports."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def upsert_standard_cost_seed(
        self, seed: StandardCostSeed, actor_id: UUID
    ) -> StandardCostSeed:
        async with self._database.session() as session, session.begin():
            return await PricingPolicyRepository(
                session, company_id=seed.company_id
            ).upsert_standard_cost_seed(seed, actor_id=actor_id)

    async def create_minimum_margin_policy(
        self, policy: MinimumMarginPolicy, actor_id: UUID
    ) -> MinimumMarginPolicy:
        async with self._database.session() as session, session.begin():
            return await PricingPolicyRepository(
                session, company_id=policy.company_id
            ).create_minimum_margin_policy(policy, actor_id=actor_id)

    async def standard_cost_seed(
        self, company_id: UUID, product_id: UUID
    ) -> StandardCostSeed | None:
        async with self._database.session() as session:
            return await PricingPolicyRepository(
                session, company_id=company_id
            ).standard_cost_seed(product_id)

    async def active_minimum_margin_policy(
        self, company_id: UUID
    ) -> MinimumMarginPolicy | None:
        async with self._database.session() as session:
            return await PricingPolicyRepository(
                session, company_id=company_id
            ).active_minimum_margin_policy()


__all__ = ["PostgresPricingPolicies"]
