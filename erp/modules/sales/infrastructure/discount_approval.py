"""Persist the M15 side of an M22 discount approval request."""

from uuid import UUID

from erp.modules.sales.application.discount_approval import (
    DiscountApprovalStore,
    RequestDiscountApproval,
)
from erp.modules.sales.application.lifecycle import SalesQuoteMutationResult
from erp.modules.sales.application.quotes import SalesQuoteDetail
from erp.modules.sales.infrastructure.lifecycle import _effects
from erp.modules.sales.infrastructure.repository import SalesQuoteRepository
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail


class PostgresDiscountApproval(DiscountApprovalStore):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def attach(
        self,
        command: RequestDiscountApproval,
        workflow_instance_id: UUID,
        actor_id: UUID,
    ) -> SalesQuoteMutationResult:
        async with self._database.session() as session, session.begin():
            repository = SalesQuoteRepository(session, company_id=command.company_id)
            before = await repository.get(command.quote_id)
            if before is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND", message="Sales quote not found.", status_code=404
                )
            if before.version != command.expected_version:
                raise OptimisticLockError(expected_version=command.expected_version)
            try:
                changed = before.request_discount_approval(workflow_instance_id)
            except ValueError as error:
                raise ApplicationError(
                    code="BUSINESS_VALIDATION_ERROR",
                    message="Invalid discount approval request.",
                    status_code=422,
                    details=[ErrorDetail(message=str(error))],
                ) from error
            changed = await repository.save(changed, actor_id=actor_id)
            event_id, audit_id = await _effects(
                session,
                before,
                changed,
                "SalesDiscountApprovalRequested",
                command.metadata,
                actor_id,
                None,
            )
        return SalesQuoteMutationResult(SalesQuoteDetail(changed, ()), event_id, audit_id)


__all__ = ["PostgresDiscountApproval"]
