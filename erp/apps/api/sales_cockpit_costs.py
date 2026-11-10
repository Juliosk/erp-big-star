"""Composition adapter exposing M9 standard costs to the Sales read model."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from erp.modules.pricing.infrastructure.price_list_model import StandardCostSeedModel
from erp.platform.database import Database


class PostgresSalesCockpitCostProvider:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def standard_costs(
        self,
        company_id: UUID,
        product_ids: frozenset[UUID],
    ) -> dict[UUID, Decimal]:
        if not product_ids:
            return {}
        async with self._database.session() as session:
            rows = (
                await session.execute(
                    select(
                        StandardCostSeedModel.product_id,
                        StandardCostSeedModel.cost_amount,
                    ).where(
                        StandardCostSeedModel.company_id == company_id,
                        StandardCostSeedModel.product_id.in_(product_ids),
                    )
                )
            ).all()
        return {row[0]: row[1] for row in rows}


__all__ = ["PostgresSalesCockpitCostProvider"]
