"""Customer 360 read model assembled inside the M14 application boundary."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.application.permissions import CUSTOMER_READ, CustomerAuthorization
from erp.modules.customer.domain import Customer, CustomerAddress, CustomerContact
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class CustomerGroupSummary:
    id: UUID
    code: str
    name: str
    active: bool


@dataclass(frozen=True, slots=True)
class CustomerDuplicateSummary:
    id: UUID
    source_customer_id: UUID
    candidate_customer_id: UUID
    confidence: int
    reason_codes: tuple[str, ...]
    status: str


@dataclass(frozen=True, slots=True)
class CustomerMergeRequestSummary:
    id: UUID
    source_customer_id: UUID
    candidate_customer_id: UUID
    surviving_customer_id: UUID
    status: str
    version: int


@dataclass(frozen=True, slots=True)
class CustomerMergeStatus:
    duplicate_candidates: tuple[CustomerDuplicateSummary, ...]
    pending_merge_requests: tuple[CustomerMergeRequestSummary, ...]


@dataclass(frozen=True, slots=True)
class Customer360Snapshot:
    customer: Customer
    contacts: tuple[CustomerContact, ...]
    addresses: tuple[CustomerAddress, ...]
    groups: tuple[CustomerGroupSummary, ...]
    merge_status: CustomerMergeStatus


class Customer360Directory(Protocol):
    async def get(self, company_id: UUID, customer_id: UUID) -> Customer360Snapshot | None: ...


class Customer360Service:
    def __init__(
        self, directory: Customer360Directory, authorization: CustomerAuthorization
    ) -> None:
        self._directory = directory
        self._authorization = authorization

    async def get(
        self, context: SecurityContext, company_id: UUID, customer_id: UUID
    ) -> Customer360Snapshot:
        await self._authorization.require(context, company_id, CUSTOMER_READ)
        snapshot = await self._directory.get(company_id, customer_id)
        if snapshot is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Customer not found.", status_code=404
            )
        return snapshot


__all__ = [
    "Customer360Directory",
    "Customer360Service",
    "Customer360Snapshot",
    "CustomerDuplicateSummary",
    "CustomerGroupSummary",
    "CustomerMergeRequestSummary",
    "CustomerMergeStatus",
]
