"""Read-only pricing snapshot queries for Cockpit and auditability."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.pricing.application.commands import PricingPage
from erp.modules.pricing.application.permissions import PRICING_SIMULATE, PricingAuthorization
from erp.modules.pricing.domain import LEGACY_OPENING


@dataclass(frozen=True, slots=True)
class PricingSnapshotView:
    id: UUID
    company_id: UUID
    product_id: UUID
    price_list_id: UUID | None
    price_list_version_id: UUID | None
    cost_source: str
    cost_amount: Decimal | None
    target_margin: Decimal | None
    minimum_margin: Decimal | None
    calculated_price: Decimal
    rounded_price: Decimal
    currency: str
    source: str
    created_at: datetime


class PricingSnapshotStore(Protocol):
    async def list_snapshots(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        product_id: UUID | None = None,
    ) -> PricingPage[PricingSnapshotView]: ...


class PricingSnapshotQueryService:
    """Expose immutable pricing decisions through a company-scoped port."""

    def __init__(self, store: PricingSnapshotStore, authorization: PricingAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def list_snapshots(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        product_id: UUID | None = None,
    ) -> PricingPage[PricingSnapshotView]:
        await self._authorization.require(context, company_id, PRICING_SIMULATE)
        return await self._store.list_snapshots(
            company_id, page=page, page_size=page_size, product_id=product_id
        )


def snapshot_view_from_values(
    *,
    snapshot_id: UUID,
    company_id: UUID,
    product_id: UUID,
    price_list_id: UUID | None,
    price_list_version_id: UUID | None,
    cost_reference: dict[str, object] | None,
    target_margin: Decimal | None,
    minimum_margin: Decimal | None,
    calculated_price: Decimal,
    rounded_price: Decimal,
    currency: str,
    source: str,
    created_at: datetime,
) -> PricingSnapshotView:
    cost_source = str((cost_reference or {}).get("source") or LEGACY_OPENING)
    amount = (cost_reference or {}).get("amount")
    cost_amount = Decimal(str(amount)) if amount is not None else None
    return PricingSnapshotView(
        id=snapshot_id,
        company_id=company_id,
        product_id=product_id,
        price_list_id=price_list_id,
        price_list_version_id=price_list_version_id,
        cost_source=cost_source,
        cost_amount=cost_amount,
        target_margin=target_margin,
        minimum_margin=minimum_margin,
        calculated_price=calculated_price,
        rounded_price=rounded_price,
        currency=currency,
        source=source,
        created_at=created_at,
    )


__all__ = [
    "PricingSnapshotQueryService",
    "PricingSnapshotStore",
    "PricingSnapshotView",
    "snapshot_view_from_values",
]
