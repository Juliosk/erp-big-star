"""Public contracts exposed by M9 Pricing to other bounded contexts."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PricingResolutionRequest:
    company_id: UUID
    product_id: UUID
    quantity: Decimal
    price_list_id: UUID | None = None
    customer_id: UUID | None = None
    customer_group_id: UUID | None = None
    channel: str | None = None


@dataclass(frozen=True, slots=True)
class PricingResolution:
    pricing_snapshot_id: UUID
    company_id: UUID
    product_id: UUID
    quantity: Decimal
    currency: str
    unit_price: Decimal
    total_price: Decimal
    minimum_price: Decimal | None
    price_list_id: UUID
    price_list_version_id: UUID
    minimum_margin: Decimal | None
    effective_margin: Decimal | None
    source: str


class PricingResolutionService(Protocol):
    async def resolve(self, request: PricingResolutionRequest) -> PricingResolution: ...


__all__ = ["PricingResolution", "PricingResolutionRequest", "PricingResolutionService"]
