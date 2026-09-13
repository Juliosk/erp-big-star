"""Public pricing request and response schemas."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.pricing.domain import PriceListStatus, PriceListVersionStatus, PriceType


class PageMetadata(BaseModel):
    page: int
    page_size: int
    has_more: bool


class PriceListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    price_type: PriceType
    currency: str
    status: PriceListStatus
    version: int


class PriceListItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    price: str
    minimum_price: str | None
    target_margin: str | None
    currency: str


class PriceListVersionResponse(BaseModel):
    id: UUID
    company_id: UUID
    price_list_id: UUID
    version_number: int
    status: PriceListVersionStatus
    valid_from: date
    valid_to: date | None
    source: str
    activated_at: datetime | None
    version: int
    items: list[PriceListItemResponse]


class PriceListListResponse(BaseModel):
    data: list[PriceListResponse]
    meta: PageMetadata


class PriceListVersionListResponse(BaseModel):
    data: list[PriceListVersionResponse]
    meta: PageMetadata


class PriceListVersionCommandResponse(BaseModel):
    price_list_version: PriceListVersionResponse
    event_id: UUID | None = None
    audit_event_id: UUID | None = None
    idempotency_replayed: bool = False


class ResolvePricingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    price_list_id: UUID | None = None
    customer_id: UUID | None = None
    customer_group_id: UUID | None = None
    channel: str | None = Field(default=None, min_length=1, max_length=32)


class SimulatePricingRequest(ResolvePricingRequest):
    proposed_unit_price: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)


class PricingResolutionResponse(BaseModel):
    pricing_snapshot_id: UUID
    company_id: UUID
    product_id: UUID
    quantity: str
    currency: str
    unit_price: str
    total_price: str
    minimum_price: str | None
    price_list_id: UUID
    price_list_version_id: UUID
    minimum_margin: str | None
    effective_margin: str | None
    source: str
    persisted: bool = True


class CreatePriceListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    price_type: PriceType = PriceType.BASE
    currency: str = "BRL"


class CreatePriceListItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    price_amount: Decimal = Field(max_digits=18, decimal_places=2)
    minimum_price_amount: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    target_margin: Decimal | None = Field(default=None, ge=0, le=1, max_digits=8, decimal_places=4)


class CreatePriceListVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    valid_from: date
    valid_to: date | None = None
    source: str = Field(default="MANUAL", min_length=1, max_length=32)
    items: list[CreatePriceListItemRequest] = Field(default_factory=list, max_length=500)


__all__ = [
    "CreatePriceListItemRequest",
    "CreatePriceListRequest",
    "CreatePriceListVersionRequest",
    "PageMetadata",
    "PriceListItemResponse",
    "PriceListListResponse",
    "PriceListResponse",
    "PriceListVersionCommandResponse",
    "PriceListVersionListResponse",
    "PriceListVersionResponse",
    "PricingResolutionResponse",
    "ResolvePricingRequest",
    "SimulatePricingRequest",
]
