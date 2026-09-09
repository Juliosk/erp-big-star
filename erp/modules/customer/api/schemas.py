"""Public customer responses, never ORM objects."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from erp.modules.customer.domain import CustomerStatus, CustomerType, TaxIdKind


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    customer_type: CustomerType
    identity_type: TaxIdKind
    identity_value: str
    identity_ref: str
    legal_name: str
    trade_name: str | None
    status: CustomerStatus
    version: int


class PageMetadata(BaseModel):
    page: int
    page_size: int
    has_more: bool


class CustomerListResponse(BaseModel):
    data: list[CustomerResponse]
    meta: PageMetadata


__all__ = ["CustomerListResponse", "CustomerResponse", "PageMetadata"]
