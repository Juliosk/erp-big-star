"""Application service for concurrent M22 workflow approval decisions."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.workflow.application.instances import WorkflowInstanceDetail
from erp.modules.workflow.application.permissions import (
    WORKFLOW_APPROVAL_DECIDE,
    WorkflowAuthorization,
)
from erp.modules.workflow.domain import ApprovalDecision, ApprovalDecisionKind
from erp.modules.workflow.domain.support import normalize_code
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class CommandMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None


@dataclass(frozen=True, slots=True)
class DecideWorkflowInstance:
    company_id: UUID
    workflow_instance_id: UUID
    step_instance_id: UUID
    expected_version: int
    decision: ApprovalDecisionKind
    reason_code: str | None
    comment: str | None
    metadata: CommandMetadata


@dataclass(frozen=True, slots=True)
class WorkflowDecisionResult:
    detail: WorkflowInstanceDetail
    decision: ApprovalDecision
    event_id: UUID | None = None
    audit_event_id: UUID | None = None


class WorkflowDecisionStore(Protocol):
    async def decide(
        self,
        command: DecideWorkflowInstance,
        *,
        actor_id: UUID,
        actor_permissions: frozenset[str],
    ) -> WorkflowDecisionResult: ...


class WorkflowDecisionService:
    """Authorize and dispatch approval decisions to the transactional store."""

    def __init__(
        self,
        store: WorkflowDecisionStore,
        authorization: WorkflowAuthorization,
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def decide(
        self,
        context: SecurityContext,
        command: DecideWorkflowInstance,
    ) -> WorkflowDecisionResult:
        await self._authorization.require(
            context, command.company_id, WORKFLOW_APPROVAL_DECIDE, write=True
        )
        try:
            if command.reason_code is not None:
                normalize_code(command.reason_code, "reason_code", max_length=64)
            if command.comment is not None and len(command.comment.strip()) > 500:
                raise ValueError("comment must be at most 500 characters.")
        except ValueError as error:
            raise _validation(str(error)) from error
        return await self._store.decide(
            command,
            actor_id=context.principal.user_id,
            actor_permissions=frozenset(str(permission) for permission in context.permissions),
        )


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid workflow decision data.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = [
    "CommandMetadata",
    "DecideWorkflowInstance",
    "WorkflowDecisionResult",
    "WorkflowDecisionService",
    "WorkflowDecisionStore",
]
