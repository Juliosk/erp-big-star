"""Public customer responses, never ORM objects."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from erp.modules.customer.application.customer360 import (
    Customer360Snapshot,
    CustomerDuplicateSummary,
    CustomerGroupSummary,
    CustomerMergeRequestSummary,
)
from erp.modules.customer.domain import (
    CustomerAddress,
    CustomerContact,
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


class CustomerContactResponse(BaseModel):
    id: UUID
    company_id: UUID
    customer_id: UUID
    role: str
    kind: str
    value: str
    name: str | None
    is_primary: bool

    @classmethod
    def from_domain(cls, contact: CustomerContact) -> CustomerContactResponse:
        return cls(
            id=contact.id,
            company_id=contact.company_id,
            customer_id=contact.customer_id,
            role=contact.role,
            kind=contact.kind,
            value=contact.value,
            name=contact.name,
            is_primary=contact.is_primary,
        )


class CustomerAddressResponse(BaseModel):
    id: UUID
    company_id: UUID
    customer_id: UUID
    role: str
    line1: str
    city: str
    state: str
    postal_code: str
    country_code: str
    line2: str | None
    district: str | None
    is_primary: bool

    @classmethod
    def from_domain(cls, address: CustomerAddress) -> CustomerAddressResponse:
        return cls(
            id=address.id,
            company_id=address.company_id,
            customer_id=address.customer_id,
            role=address.role,
            line1=address.line1,
            city=address.city,
            state=address.state,
            postal_code=address.postal_code,
            country_code=address.country_code,
            line2=address.line2,
            district=address.district,
            is_primary=address.is_primary,
        )


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


class Customer360GroupResponse(BaseModel):
    id: UUID
    code: str
    name: str
    active: bool

    @classmethod
    def from_summary(cls, group: CustomerGroupSummary) -> Customer360GroupResponse:
        return cls(id=group.id, code=group.code, name=group.name, active=group.active)


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


class Customer360DuplicateResponse(BaseModel):
    id: UUID
    source_customer_id: UUID
    candidate_customer_id: UUID
    confidence: int
    reason_codes: list[str]
    status: str

    @classmethod
    def from_summary(cls, duplicate: CustomerDuplicateSummary) -> Customer360DuplicateResponse:
        return cls(
            id=duplicate.id,
            source_customer_id=duplicate.source_customer_id,
            candidate_customer_id=duplicate.candidate_customer_id,
            confidence=duplicate.confidence,
            reason_codes=list(duplicate.reason_codes),
            status=duplicate.status,
        )


class Customer360MergeRequestResponse(BaseModel):
    id: UUID
    source_customer_id: UUID
    candidate_customer_id: UUID
    surviving_customer_id: UUID
    status: str
    version: int

    @classmethod
    def from_summary(
        cls, merge_request: CustomerMergeRequestSummary
    ) -> Customer360MergeRequestResponse:
        return cls(
            id=merge_request.id,
            source_customer_id=merge_request.source_customer_id,
            candidate_customer_id=merge_request.candidate_customer_id,
            surviving_customer_id=merge_request.surviving_customer_id,
            status=merge_request.status,
            version=merge_request.version,
        )


class Customer360MergeStatusResponse(BaseModel):
    duplicate_candidates: list[Customer360DuplicateResponse]
    pending_merge_requests: list[Customer360MergeRequestResponse]


class Customer360Response(BaseModel):
    customer: CustomerResponse
    contacts: list[CustomerContactResponse]
    addresses: list[CustomerAddressResponse]
    groups: list[Customer360GroupResponse]
    merge_status: Customer360MergeStatusResponse

    @classmethod
    def from_snapshot(cls, snapshot: Customer360Snapshot) -> Customer360Response:
        return cls(
            customer=CustomerResponse.model_validate(snapshot.customer),
            contacts=[
                CustomerContactResponse.from_domain(contact) for contact in snapshot.contacts
            ],
            addresses=[
                CustomerAddressResponse.from_domain(address) for address in snapshot.addresses
            ],
            groups=[Customer360GroupResponse.from_summary(group) for group in snapshot.groups],
            merge_status=Customer360MergeStatusResponse(
                duplicate_candidates=[
                    Customer360DuplicateResponse.from_summary(candidate)
                    for candidate in snapshot.merge_status.duplicate_candidates
                ],
                pending_merge_requests=[
                    Customer360MergeRequestResponse.from_summary(merge_request)
                    for merge_request in snapshot.merge_status.pending_merge_requests
                ],
            ),
        )


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
    "Customer360DuplicateResponse",
    "Customer360GroupResponse",
    "Customer360MergeRequestResponse",
    "Customer360MergeStatusResponse",
    "Customer360Response",
    "CustomerAddressResponse",
    "CustomerContactResponse",
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
