"""PostgreSQL read model for M9 pricing snapshots."""

from uuid import UUID

from sqlalchemy import select

from erp.modules.pricing.application import PricingPage, PricingSnapshotStore, PricingSnapshotView
from erp.modules.pricing.application.snapshots import snapshot_view_from_values
from erp.modules.pricing.infrastructure.price_list_model import PricingSnapshotModel
from erp.platform.database import Database


class PostgresPricingSnapshots(PricingSnapshotStore):
    """Read immutable snapshot rows by selected company."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_snapshots(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        product_id: UUID | None = None,
    ) -> PricingPage[PricingSnapshotView]:
        if type(page) is not int or page < 1:
            raise ValueError("page must be a positive integer.")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be an integer between 1 and 100.")
        async with self._database.session() as session:
            statement = select(PricingSnapshotModel).where(
                PricingSnapshotModel.company_id == company_id
            )
            if product_id is not None:
                statement = statement.where(PricingSnapshotModel.product_id == product_id)
            offset = (page - 1) * page_size
            result = await session.scalars(
                statement.order_by(
                    PricingSnapshotModel.created_at.desc(), PricingSnapshotModel.id
                )
                .limit(page_size + 1)
                .offset(offset)
                .execution_options(populate_existing=True)
            )
            rows = list(result)
            return PricingPage(
                tuple(_snapshot_view(row) for row in rows[:page_size]),
                page,
                page_size,
                len(rows) > page_size,
            )


def _snapshot_view(model: PricingSnapshotModel) -> PricingSnapshotView:
    return snapshot_view_from_values(
        snapshot_id=model.id,
        company_id=model.company_id,
        product_id=model.product_id,
        price_list_id=model.price_list_id,
        price_list_version_id=model.price_list_version_id,
        cost_reference=model.cost_reference,
        target_margin=model.target_margin,
        minimum_margin=model.minimum_margin,
        calculated_price=model.calculated_price_amount,
        rounded_price=model.rounded_price_amount,
        currency=model.currency,
        source=model.source,
        created_at=model.created_at,
    )


__all__ = ["PostgresPricingSnapshots"]
