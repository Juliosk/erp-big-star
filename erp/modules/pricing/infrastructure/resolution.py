"""PostgreSQL adapter for M9 price resolution."""

from uuid import UUID, uuid4

from sqlalchemy import case, select

from erp.modules.pricing.application.resolution import (
    PricingCandidate,
    PricingResolutionStore,
    PricingSnapshotDraft,
)
from erp.modules.pricing.contracts import PricingResolutionRequest
from erp.modules.pricing.domain import (
    MinimumMarginPolicy,
    PriceListVersionStatus,
    PriceType,
    StandardCostSeed,
)
from erp.modules.pricing.infrastructure.policy_repository import _minimum_margin, _standard_cost
from erp.modules.pricing.infrastructure.price_list_model import (
    MinimumMarginPolicyModel,
    PriceListItemModel,
    PriceListModel,
    PriceListVersionModel,
    PricingSnapshotModel,
    StandardCostSeedModel,
)
from erp.modules.pricing.infrastructure.price_list_repository import _price_item
from erp.platform.database import Database


class PostgresPricingResolver(PricingResolutionStore):
    """Resolve active list prices without leaking SQLAlchemy beyond infrastructure."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def find_candidate(
        self,
        request: PricingResolutionRequest,
    ) -> PricingCandidate | None:
        async with self._database.session() as session:
            type_priority = case(
                (
                    PriceListModel.price_type == PriceType.CUSTOMER_GROUP,
                    0 if request.customer_group_id is not None else 30,
                ),
                (
                    PriceListModel.price_type == PriceType.CHANNEL,
                    10 if request.channel is not None else 30,
                ),
                (
                    PriceListModel.price_type == PriceType.BASE,
                    20,
                ),
                else_=40,
            )
            statement = (
                select(PriceListModel, PriceListVersionModel, PriceListItemModel)
                .join(
                    PriceListVersionModel,
                    (PriceListVersionModel.company_id == PriceListModel.company_id)
                    & (PriceListVersionModel.price_list_id == PriceListModel.id),
                )
                .join(
                    PriceListItemModel,
                    (PriceListItemModel.company_id == PriceListVersionModel.company_id)
                    & (
                        PriceListItemModel.price_list_version_id
                        == PriceListVersionModel.id
                    ),
                )
                .where(
                    PriceListModel.company_id == request.company_id,
                    PriceListItemModel.product_id == request.product_id,
                    PriceListVersionModel.status == PriceListVersionStatus.ACTIVE,
                )
                .order_by(type_priority, PriceListVersionModel.version_number.desc())
                .limit(1)
                .execution_options(populate_existing=True)
            )
            if request.price_list_id is not None:
                statement = statement.where(PriceListModel.id == request.price_list_id)
            row = (await session.execute(statement)).first()
            if row is None:
                return None
            price_list, version, item = row._tuple()
            return PricingCandidate(
                price_list_id=price_list.id,
                price_list_version_id=version.id,
                source=f"PRICE_LIST:{price_list.price_type}",
                item=_price_item(item),
            )

    async def standard_cost_seed(
        self, company_id: UUID, product_id: UUID
    ) -> StandardCostSeed | None:
        async with self._database.session() as session:
            model = await session.scalar(
                select(StandardCostSeedModel).where(
                    StandardCostSeedModel.company_id == company_id,
                    StandardCostSeedModel.product_id == product_id,
                )
            )
            return None if model is None else _standard_cost(model)

    async def active_minimum_margin_policy(
        self, company_id: UUID
    ) -> MinimumMarginPolicy | None:
        async with self._database.session() as session:
            model = await session.scalar(
                select(MinimumMarginPolicyModel)
                .where(
                    MinimumMarginPolicyModel.company_id == company_id,
                    MinimumMarginPolicyModel.status == "ACTIVE",
                )
                .order_by(MinimumMarginPolicyModel.created_at.desc(), MinimumMarginPolicyModel.id)
                .limit(1)
            )
            return None if model is None else _minimum_margin(model)

    async def create_pricing_snapshot(
        self, draft: PricingSnapshotDraft, actor_id: UUID
    ) -> UUID:
        async with self._database.session() as session, session.begin():
            snapshot_id = uuid4()
            session.add(
                PricingSnapshotModel(
                    id=snapshot_id,
                    company_id=draft.company_id,
                    product_id=draft.product_id,
                    price_list_id=draft.price_list_id,
                    price_list_version_id=draft.price_list_version_id,
                    cost_reference={
                        "source": draft.cost.source,
                        "standard_cost_seed_id": str(draft.cost.id),
                        "product_id": str(draft.cost.product_id),
                        "amount": f"{draft.cost.cost.amount:.2f}",
                        "currency": draft.cost.cost.currency,
                        "version": draft.cost.version,
                    },
                    tax_reference=None,
                    commission_reference=None,
                    fee_reference=None,
                    freight_reference=None,
                    target_margin=(
                        None
                        if draft.target_margin is None
                        else draft.target_margin.value
                    ),
                    minimum_margin=(
                        None
                        if draft.minimum_margin is None
                        else draft.minimum_margin.value
                    ),
                    calculated_price_amount=draft.unit_price.amount,
                    rounded_price_amount=draft.unit_price.amount,
                    currency=draft.unit_price.currency,
                    source=draft.source,
                    created_by=actor_id,
                )
            )
            await session.flush()
            return snapshot_id


__all__ = ["PostgresPricingResolver"]
