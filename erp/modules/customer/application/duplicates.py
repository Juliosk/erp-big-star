"""Duplicate detection and merge request application services."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.application.commands import CommandMetadata
from erp.modules.customer.application.permissions import (
    CUSTOMER_MERGE,
    CUSTOMER_READ,
    CustomerAuthorization,
)
from erp.modules.customer.domain import CustomerDuplicateCandidate, CustomerMergeRequest
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class RequestCustomerMerge:
    company_id: UUID
    source_customer_id: UUID
    candidate_customer_id: UUID
    surviving_customer_id: UUID
    reason: str
    metadata: CommandMetadata


@dataclass(frozen=True, slots=True)
class CustomerMergeRequestResult:
    merge_request: CustomerMergeRequest
    event_id: UUID
    audit_event_id: UUID


class CustomerDuplicateStore(Protocol):
    async def detect(
        self, company_id: UUID, customer_id: UUID, actor_id: UUID
    ) -> tuple[CustomerDuplicateCandidate, ...]: ...

    async def request_merge(
        self, command: RequestCustomerMerge, actor_id: UUID
    ) -> CustomerMergeRequestResult: ...


class CustomerDuplicateService:
    def __init__(self, store: CustomerDuplicateStore, authorization: CustomerAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def detect(
        self, context: SecurityContext, company_id: UUID, customer_id: UUID
    ) -> tuple[CustomerDuplicateCandidate, ...]:
        await self._authorization.require(context, company_id, CUSTOMER_READ)
        return await self._store.detect(company_id, customer_id, context.principal.user_id)

    async def request_merge(
        self, context: SecurityContext, command: RequestCustomerMerge
    ) -> CustomerMergeRequestResult:
        if command.source_customer_id == command.candidate_customer_id:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid customer merge request.",
                status_code=422,
            )
        await self._authorization.require(context, command.company_id, CUSTOMER_MERGE, write=True)
        try:
            return await self._store.request_merge(command, context.principal.user_id)
        except ValueError as error:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid customer merge request.",
                status_code=422,
            ) from error


__all__ = [
    "CustomerDuplicateService",
    "CustomerDuplicateStore",
    "CustomerMergeRequestResult",
    "RequestCustomerMerge",
]
