"""HTTP contracts for M15 sales quotes."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.sales.domain import SalesQuoteStatus


class CreateSalesQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    number: str = Field(min_length=1, max_length=64)
    customer_id: UUID
    currency: str = Field(default="BRL", min_length=3, max_length=3)


class QuoteItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal


class QuoteRevisionResponse(BaseModel):
    id: UUID
    revision_number: int
    gross_amount: Decimal
    discount_amount: Decimal
    net_amount: Decimal
    pricing_snapshot_refs: list[UUID]
    items: list[QuoteItemResponse]


class SalesQuoteResponse(BaseModel):
    id: UUID
    company_id: UUID
    number: str
    customer_id: UUID
    seller_id: UUID
    currency: str
    status: SalesQuoteStatus
    current_revision_number: int
    workflow_instance_id: UUID | None
    converted_order_id: UUID | None
    version: int


class SalesQuoteDetailResponse(BaseModel):
    quote: SalesQuoteResponse
    revisions: list[QuoteRevisionResponse]


class PageMetadata(BaseModel):
    page: int
    page_size: int
    has_more: bool


class SalesQuoteListResponse(BaseModel):
    data: list[SalesQuoteResponse]
    meta: PageMetadata


__all__ = [
    "CreateSalesQuoteRequest",
    "PageMetadata",
    "QuoteItemResponse",
    "QuoteRevisionResponse",
    "SalesQuoteDetailResponse",
    "SalesQuoteListResponse",
    "SalesQuoteResponse",
]
