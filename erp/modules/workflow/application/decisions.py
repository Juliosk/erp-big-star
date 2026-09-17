"""Application service for concurrent M22 workflow approval decisions."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.workflow.application.instances import (
    WorkflowInstanceDetail,
    workflow_instance_detail_snapshot,
)
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

    def to_dict(self) -> dict[str, object]:
        return {
            "detail": workflow_instance_detail_snapshot(self.detail),
            "decision": approval_decision_snapshot(self.decision),
            "event_id": str(self.event_id) if self.event_id is not None else None,
            "audit_event_id": str(self.audit_event_id)
            if self.audit_event_id is not None
            else None,
        }


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


def approval_decision_snapshot(decision: ApprovalDecision) -> dict[str, object]:
    return {
        "id": str(decision.id),
        "company_id": str(decision.company_id),
        "workflow_instance_id": str(decision.workflow_instance_id),
        "step_instance_id": str(decision.step_instance_id),
        "decision": decision.decision,
        "decided_by": str(decision.decided_by),
        "decided_at": decision.decided_at.isoformat(),
        "reason_code": decision.reason_code,
        "comment": decision.comment,
    }


__all__ = [
    "CommandMetadata",
    "DecideWorkflowInstance",
    "WorkflowDecisionResult",
    "WorkflowDecisionService",
    "WorkflowDecisionStore",
    "approval_decision_snapshot",
]
