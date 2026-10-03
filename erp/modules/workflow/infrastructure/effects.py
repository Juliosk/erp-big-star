"""Audit and Outbox effects staged by M22 Workflow decisions."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.workflow.application.decisions import (
    DecideWorkflowInstance,
    WorkflowDecisionResult,
    approval_decision_snapshot,
)
from erp.modules.workflow.application.instances import (
    WorkflowInstanceDetail,
    workflow_instance_detail_snapshot,
)
from erp.modules.workflow.domain import ApprovalDecisionKind, WorkflowInstanceStatus
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

WORKFLOW_INSTANCE_APPROVED = "WorkflowInstanceApproved"
WORKFLOW_INSTANCE_REJECTED = "WorkflowInstanceRejected"
WORKFLOW_STEP_APPROVED = "WorkflowStepApproved"


class WorkflowEffects:
    """Persist observable workflow side effects in the business transaction."""

    async def record_decision(
        self,
        session: AsyncSession,
        result: WorkflowDecisionResult,
        *,
        actor_id: UUID,
        command: DecideWorkflowInstance,
        before: WorkflowInstanceDetail,
    ) -> WorkflowDecisionResult:
        event_type = _event_type(result)
        before_snapshot = workflow_instance_detail_snapshot(before)
        after_snapshot = workflow_instance_detail_snapshot(result.detail)
        decision_snapshot = approval_decision_snapshot(result.decision)
        after_snapshot["decision"] = decision_snapshot
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=result.detail.instance.company_id,
                branch_id=None,
                module="workflow",
                entity_type="workflow_instance",
                entity_id=result.detail.instance.id,
                operation=event_type,
                request_id=command.metadata.request_id,
                correlation_id=command.metadata.correlation_id,
                source_ip=command.metadata.source_ip,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                reason_code=result.decision.reason_code,
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=event_type,
            event_version=1,
            producer_module="workflow",
            producer_domain="workflow",
            aggregate_type="workflow_instance",
            aggregate_id=result.detail.instance.id,
            aggregate_version=result.detail.instance.version,
            company_id=result.detail.instance.company_id,
            branch_id=None,
            correlation_id=command.metadata.correlation_id,
            request_id=command.metadata.request_id,
            causation_id=None,
            payload={
                "company_id": str(result.detail.instance.company_id),
                "workflow_instance_id": str(result.detail.instance.id),
                "definition_id": str(result.detail.instance.definition_id),
                "source_module": result.detail.instance.source_module,
                "source_type": result.detail.instance.source_type,
                "source_id": str(result.detail.instance.source_id),
                "status": result.detail.instance.status,
                "decision": decision_snapshot,
            },
        )
        await OutboxService().enqueue(session, envelope)
        if result.detail.instance.source_module == "procurement" and event_type in {
            WORKFLOW_INSTANCE_APPROVED,
            WORKFLOW_INSTANCE_REJECTED,
        }:
            decision_envelope = MessageEnvelope.new(
                message_kind=MessageKind.DOMAIN_EVENT,
                message_type="ApprovalDecisionMade",
                event_version=1,
                producer_module="workflow",
                producer_domain="workflow",
                aggregate_type="workflow_instance",
                aggregate_id=result.detail.instance.id,
                aggregate_version=result.detail.instance.version,
                company_id=result.detail.instance.company_id,
                branch_id=None,
                correlation_id=command.metadata.correlation_id,
                request_id=command.metadata.request_id,
                causation_id=envelope.message_id,
                payload={
                    "source_module": "procurement",
                    "source_type": result.detail.instance.source_type,
                    "source_id": str(result.detail.instance.source_id),
                    "decision": str(result.decision.decision),
                    "decided_by": str(actor_id),
                    "workflow_instance_id": str(result.detail.instance.id),
                },
            )
            await OutboxService().enqueue(session, decision_envelope)
        return WorkflowDecisionResult(
            detail=result.detail,
            decision=result.decision,
            event_id=envelope.message_id,
            audit_event_id=audit_id,
        )


def _event_type(result: WorkflowDecisionResult) -> str:
    if result.decision.decision is ApprovalDecisionKind.REJECTED:
        return WORKFLOW_INSTANCE_REJECTED
    if result.detail.instance.status is WorkflowInstanceStatus.APPROVED:
        return WORKFLOW_INSTANCE_APPROVED
    return WORKFLOW_STEP_APPROVED


__all__ = [
    "WORKFLOW_INSTANCE_APPROVED",
    "WORKFLOW_INSTANCE_REJECTED",
    "WORKFLOW_STEP_APPROVED",
    "WorkflowEffects",
]
