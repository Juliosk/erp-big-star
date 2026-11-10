"""Read-only contracts for the multichannel Sales operations cockpit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.application.permissions import SALES_ORDERS_READ, SalesAuthorization


@dataclass(frozen=True, slots=True)
class SalesCockpitOrder:
    id: UUID
    external_order_id: str
    marketplace: str
    status: str
    reconciliation_status: str
    total_amount: Decimal
    margin_amount: Decimal | None
    margin_percent: Decimal | None
    shipment_status: str | None
    tracking_code: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SalesChannelPulse:
    marketplace: str
    order_count: int
    pending_count: int
    paid_count: int
    shipped_count: int
    cancelled_count: int
    sales_amount: Decimal
    margin_amount: Decimal | None
    margin_percent: Decimal | None
    margin_pending_orders: int


@dataclass(frozen=True, slots=True)
class SalesCockpitSnapshot:
    company_id: UUID
    generated_at: datetime
    channels: tuple[SalesChannelPulse, ...]
    orders: tuple[SalesCockpitOrder, ...]
    reconciled_orders: int
    margin_pending_orders: int


class SalesCockpitReader(Protocol):
    async def load(
        self,
        company_id: UUID,
        *,
        as_of: datetime,
        limit: int,
    ) -> SalesCockpitSnapshot: ...


class SalesCockpitCostProvider(Protocol):
    async def standard_costs(
        self,
        company_id: UUID,
        product_ids: frozenset[UUID],
    ) -> dict[UUID, Decimal]: ...


class SalesCockpitService:
    """Authorize and load a tenant-bound multichannel commercial snapshot."""

    def __init__(self, reader: SalesCockpitReader, authorization: SalesAuthorization) -> None:
        self._reader = reader
        self._authorization = authorization

    async def snapshot(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        limit: int = 50,
        as_of: datetime | None = None,
    ) -> SalesCockpitSnapshot:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200.")
        await self._authorization.require(context, company_id, SALES_ORDERS_READ)
        instant = as_of or datetime.now(UTC)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware.")
        return await self._reader.load(company_id, as_of=instant, limit=limit)


__all__ = [
    "SalesChannelPulse",
    "SalesCockpitCostProvider",
    "SalesCockpitOrder",
    "SalesCockpitReader",
    "SalesCockpitService",
    "SalesCockpitSnapshot",
]
