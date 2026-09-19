"""M15 port and orchestration for commercial discount approval through M22."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.application.lifecycle import CommandMetadata, SalesQuoteMutationResult
from erp.modules.sales.application.permissions import SALES_DISCOUNT_REQUEST, SalesAuthorization
from erp.modules.sales.application.quotes import SalesQuoteStore
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class RequestDiscountApproval:
    company_id: UUID
    quote_id: UUID
    expected_version: int
    metadata: CommandMetadata


class DiscountWorkflowGateway(Protocol):
    async def open(
        self,
        context: SecurityContext,
        *,
        company_id: UUID,
        quote_id: UUID,
        source_fingerprint: str,
    ) -> UUID: ...


class DiscountApprovalStore(Protocol):
    async def attach(
        self,
        command: RequestDiscountApproval,
        workflow_instance_id: UUID,
        actor_id: UUID,
    ) -> SalesQuoteMutationResult: ...


class DiscountApprovalService:
    def __init__(
        self,
        quotes: SalesQuoteStore,
        store: DiscountApprovalStore,
        workflows: DiscountWorkflowGateway,
        authorization: SalesAuthorization,
    ) -> None:
        self._quotes = quotes
        self._store = store
        self._workflows = workflows
        self._authorization = authorization

    async def request(
        self, context: SecurityContext, command: RequestDiscountApproval
    ) -> SalesQuoteMutationResult:
        await self._authorization.require(
            context, command.company_id, SALES_DISCOUNT_REQUEST, write=True
        )
        detail = await self._quotes.get(command.company_id, command.quote_id)
        if detail is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Sales quote not found.", status_code=404
            )
        if detail.quote.version != command.expected_version:
            from erp.platform.concurrency import OptimisticLockError

            raise OptimisticLockError(expected_version=command.expected_version)
        if not detail.revisions or detail.revisions[-1].discount_amount <= 0:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Discount approval requires a discounted current revision.",
                status_code=422,
                details=[ErrorDetail(message="No discount exception was found.")],
            )
        workflow_id = await self._workflows.open(
            context,
            company_id=command.company_id,
            quote_id=command.quote_id,
            source_fingerprint=f"quote:{command.quote_id}:v{command.expected_version}",
        )
        return await self._store.attach(
            command, workflow_id, context.principal.user_id
        )


__all__ = [
    "DiscountApprovalService",
    "DiscountApprovalStore",
    "DiscountWorkflowGateway",
    "RequestDiscountApproval",
]
