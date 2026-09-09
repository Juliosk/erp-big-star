"""Public customer responses, never ORM objects."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from erp.modules.customer.domain import (
    CustomerDuplicateCandidate,
    CustomerGroup,
    CustomerMergeRequest,
    CustomerStatus,
    CustomerType,
    TaxIdKind,
)


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


class CustomerDuplicateCandidateResponse(BaseModel):
    id: UUID
    company_id: UUID
    source_customer_id: UUID
    candidate_customer_id: UUID
    confidence: int
    reason_codes: list[str]

    @classmethod
    def from_domain(
        cls, candidate: CustomerDuplicateCandidate
    ) -> CustomerDuplicateCandidateResponse:
        return cls(
            id=candidate.id,
            company_id=candidate.company_id,
            source_customer_id=candidate.source_customer_id,
            candidate_customer_id=candidate.candidate_customer_id,
            confidence=candidate.confidence,
            reason_codes=[reason.value for reason in candidate.reason_codes],
        )


class CustomerDuplicateListResponse(BaseModel):
    data: list[CustomerDuplicateCandidateResponse]


class CustomerMergeRequestResponse(BaseModel):
    id: UUID
    company_id: UUID
    source_customer_id: UUID
    candidate_customer_id: UUID
    surviving_customer_id: UUID
    status: str
    reason: str
    version: int
    event_id: UUID
    audit_event_id: UUID

    @classmethod
    def from_domain(
        cls, merge_request: CustomerMergeRequest, *, event_id: UUID, audit_event_id: UUID
    ) -> CustomerMergeRequestResponse:
        return cls(
            id=merge_request.id,
            company_id=merge_request.company_id,
            source_customer_id=merge_request.source_customer_id,
            candidate_customer_id=merge_request.candidate_customer_id,
            surviving_customer_id=merge_request.surviving_customer_id,
            status=merge_request.status,
            reason=merge_request.reason,
            version=merge_request.version,
            event_id=event_id,
            audit_event_id=audit_event_id,
        )


__all__ = [
    "CustomerDuplicateCandidateResponse",
    "CustomerDuplicateListResponse",
    "CustomerGroupAssignmentResponse",
    "CustomerGroupListResponse",
    "CustomerGroupResponse",
    "CustomerListResponse",
    "CustomerMergeRequestResponse",
    "CustomerResponse",
    "PageMetadata",
]
