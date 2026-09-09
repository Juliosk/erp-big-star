"""Audit and Outbox effects for customer merge requests."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.customer.application.commands import CommandMetadata
from erp.modules.customer.application.duplicates import CustomerMergeRequestResult
from erp.modules.customer.domain import CustomerMergeRequest
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


def _snapshot(merge_request: CustomerMergeRequest) -> dict[str, object]:
    return {
        "id": str(merge_request.id),
        "company_id": str(merge_request.company_id),
        "source_customer_id": str(merge_request.source_customer_id),
        "candidate_customer_id": str(merge_request.candidate_customer_id),
        "surviving_customer_id": str(merge_request.surviving_customer_id),
        "status": merge_request.status,
        "reason": merge_request.reason,
        "version": merge_request.version,
    }


class CustomerMergeEffects:
    async def record_request(
        self,
        session: AsyncSession,
        merge_request: CustomerMergeRequest,
        *,
        actor_id: UUID,
        metadata: CommandMetadata,
    ) -> CustomerMergeRequestResult:
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=merge_request.company_id,
                branch_id=None,
                module="crm",
                entity_type="customer_merge",
                entity_id=merge_request.id,
                operation="MergeApprovalRequested",
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                source_ip=metadata.source_ip,
                before_snapshot=None,
                after_snapshot=_snapshot(merge_request),
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.ASYNC_REQUEST,
            message_type="MergeApprovalRequested",
            event_version=1,
            producer_module="crm",
            producer_domain="customer",
            aggregate_type="customer_merge",
            aggregate_id=merge_request.id,
            aggregate_version=merge_request.version,
            company_id=merge_request.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            request_id=metadata.request_id,
            causation_id=None,
            payload={
                "merge_request_id": str(merge_request.id),
                "domain": "customer",
            },
        )
        await OutboxService().enqueue(session, envelope)
        return CustomerMergeRequestResult(merge_request, envelope.message_id, audit_id)


__all__ = ["CustomerMergeEffects"]
