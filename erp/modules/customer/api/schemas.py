"""Public customer responses, never ORM objects."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from erp.modules.customer.domain import CustomerGroup, CustomerStatus, CustomerType, TaxIdKind


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


class CustomerGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    description: str | None
    active: bool
    version: int

    @classmethod
    def from_domain(cls, group: CustomerGroup) -> CustomerGroupResponse:
        return cls.model_validate(group)


class CustomerGroupListResponse(BaseModel):
    data: list[CustomerGroupResponse]
    meta: PageMetadata


class CustomerGroupAssignmentResponse(BaseModel):
    id: UUID
    company_id: UUID
    customer_id: UUID
    customer_group_id: UUID
    event_id: UUID
    audit_event_id: UUID


__all__ = [
    "CustomerGroupAssignmentResponse",
    "CustomerGroupListResponse",
    "CustomerGroupResponse",
    "CustomerListResponse",
    "CustomerResponse",
    "PageMetadata",
]
