"""Pure M6-to-M22 approval handoff contract with no workflow dependency."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.procurement.domain.exceptions import ProcurementDomainError
from erp.modules.procurement.domain.support import currency, money, require_uuid


class ApprovalSubjectType(StrEnum):
    PURCHASE_REQUISITION = "PURCHASE_REQUISITION"
    PURCHASE_ORDER = "PURCHASE_ORDER"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    company_id: UUID
    subject_type: ApprovalSubjectType
    subject_id: UUID
    requested_by: UUID
    amount: Decimal
    currency: str
    aggregate_version: int

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        require_uuid(self.subject_id, "subject_id")
        require_uuid(self.requested_by, "requested_by")
        if not isinstance(self.subject_type, ApprovalSubjectType):
            raise ProcurementDomainError("subject_type must be an official approval subject.")
        object.__setattr__(self, "amount", money(self.amount, "amount"))
        object.__setattr__(self, "currency", currency(self.currency))
        if type(self.aggregate_version) is not int or self.aggregate_version < 1:
            raise ProcurementDomainError("aggregate_version must be a positive integer.")

    @property
    def fingerprint(self) -> str:
        return (
            f"M6:{self.subject_type}:{self.company_id}:{self.subject_id}:v{self.aggregate_version}"
        )


@dataclass(frozen=True, slots=True)
class ApprovalLinked:
    company_id: UUID
    subject_type: ApprovalSubjectType
    subject_id: UUID
    workflow_instance_id: UUID
    aggregate_version: int

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        require_uuid(self.subject_id, "subject_id")
        require_uuid(self.workflow_instance_id, "workflow_instance_id")
        if not isinstance(self.subject_type, ApprovalSubjectType):
            raise ProcurementDomainError("subject_type must be an official approval subject.")
        if type(self.aggregate_version) is not int or self.aggregate_version < 1:
            raise ProcurementDomainError("aggregate_version must be a positive integer.")


@dataclass(frozen=True, slots=True)
class ProcurementApprovalRequested:
    event_id: UUID
    request: ApprovalRequest

    @classmethod
    def from_request(cls, request: ApprovalRequest) -> ProcurementApprovalRequested:
        if not isinstance(request, ApprovalRequest):
            raise ProcurementDomainError("request must be a validated ApprovalRequest.")
        return cls(event_id=uuid4(), request=request)

    @property
    def event_type(self) -> str:
        return "ProcurementApprovalRequested"


@dataclass(frozen=True, slots=True)
class ProcurementApprovalLinked:
    event_id: UUID
    link: ApprovalLinked

    @classmethod
    def from_link(cls, link: ApprovalLinked) -> ProcurementApprovalLinked:
        if not isinstance(link, ApprovalLinked):
            raise ProcurementDomainError("link must be a validated ApprovalLinked.")
        return cls(event_id=uuid4(), link=link)

    @property
    def event_type(self) -> str:
        return "ProcurementApprovalLinked"


__all__ = [
    "ApprovalLinked",
    "ApprovalRequest",
    "ApprovalSubjectType",
    "ProcurementApprovalLinked",
    "ProcurementApprovalRequested",
]
