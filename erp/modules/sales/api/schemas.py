"""HTTP contracts for M15 sales quotes."""

from datetime import datetime
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


class RevisionLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    pricing_snapshot_id: UUID | None = None


class ReviseSalesQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    lines: list[RevisionLineRequest] = Field(min_length=1, max_length=500)


class TransitionSalesQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    reason_code: str | None = Field(default=None, min_length=1, max_length=64)


class ConvertQuoteToOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    order_number: str = Field(min_length=1, max_length=64)


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


class SalesQuoteMutationResponse(BaseModel):
    detail: SalesQuoteDetailResponse
    event_id: UUID
    audit_event_id: UUID


class SalesOrderItemResponse(BaseModel):
    id: UUID
    quote_revision_item_id: UUID
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    pricing_snapshot_id: UUID | None


class SalesOrderResponse(BaseModel):
    id: UUID
    company_id: UUID
    number: str
    source_quote_id: UUID
    source_quote_revision_number: int
    customer_id: UUID
    seller_id: UUID
    currency: str
    status: str
    gross_amount: Decimal
    discount_amount: Decimal
    net_amount: Decimal
    version: int
    items: list[SalesOrderItemResponse]


class SalesOrderListResponse(BaseModel):
    data: list[SalesOrderResponse]
    meta: PageMetadata


class SalesOrderConversionResponse(BaseModel):
    order: SalesOrderResponse
    quote_version: int
    event_id: UUID
    audit_event_id: UUID
    idempotency_replayed: bool


class ReserveSalesOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    warehouse_id: UUID
    location_id: UUID | None = None
    lot_id: UUID | None = None
    pool_id: UUID | None = None
    reservation_kind: str = "HARD"
    expires_at: datetime | None = None


class SalesOrderReservationLineResponse(BaseModel):
    order_item_id: UUID
    product_id: UUID
    quantity: Decimal
    pricing_snapshot_id: UUID | None


class SalesOrderReservationResponse(BaseModel):
    id: UUID
    company_id: UUID
    order_id: UUID
    inventory_reservation_id: UUID | None
    status: str
    order_version: int
    version: int
    lines: list[SalesOrderReservationLineResponse]
    inventory_event_id: UUID | None = None
    audit_event_id: UUID | None = None
    idempotency_replayed: bool = False


class PageMetadata(BaseModel):
    page: int
    page_size: int
    has_more: bool


class SalesQuoteListResponse(BaseModel):
    data: list[SalesQuoteResponse]
    meta: PageMetadata


__all__ = [
    "ConvertQuoteToOrderRequest",
    "CreateSalesQuoteRequest",
    "PageMetadata",
    "QuoteItemResponse",
    "QuoteRevisionResponse",
    "ReserveSalesOrderRequest",
    "ReviseSalesQuoteRequest",
    "RevisionLineRequest",
    "SalesOrderConversionResponse",
    "SalesOrderItemResponse",
    "SalesOrderListResponse",
    "SalesOrderReservationLineResponse",
    "SalesOrderReservationResponse",
    "SalesOrderResponse",
    "SalesQuoteDetailResponse",
    "SalesQuoteListResponse",
    "SalesQuoteMutationResponse",
    "SalesQuoteResponse",
    "TransitionSalesQuoteRequest",
]
