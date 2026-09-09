"""Audit and Outbox effects for customer group segmentation."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.customer.application.commands import CommandMetadata
from erp.modules.customer.application.groups import CustomerGroupAssignmentResult
from erp.modules.customer.domain import CustomerGroupMember
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


def _snapshot(member: CustomerGroupMember) -> dict[str, object]:
    return {
        "id": str(member.id),
        "company_id": str(member.company_id),
        "customer_id": str(member.customer_id),
        "customer_group_id": str(member.customer_group_id),
    }


class CustomerGroupEffects:
    async def record_assignment(
        self,
        session: AsyncSession,
        member: CustomerGroupMember,
        *,
        actor_id: UUID,
        metadata: CommandMetadata,
    ) -> CustomerGroupAssignmentResult:
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=member.company_id,
                branch_id=None,
                module="crm",
                entity_type="customer_group_member",
                entity_id=member.id,
                operation="CustomerGroupChanged",
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                source_ip=metadata.source_ip,
                before_snapshot=None,
                after_snapshot=_snapshot(member),
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type="CustomerGroupChanged",
            event_version=1,
            producer_module="crm",
            producer_domain="customer",
            aggregate_type="customer",
            aggregate_id=member.customer_id,
            aggregate_version=1,
            company_id=member.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            request_id=metadata.request_id,
            causation_id=None,
            payload={
                "customer_id": str(member.customer_id),
                "customer_group_id": str(member.customer_group_id),
            },
        )
        await OutboxService().enqueue(session, envelope)
        return CustomerGroupAssignmentResult(member, envelope.message_id, audit_id)


__all__ = ["CustomerGroupEffects"]
