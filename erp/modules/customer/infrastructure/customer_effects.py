"""Audit and Outbox effects staged on the customer's transaction."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.customer.application.commands import (
    CommandMetadata,
    CustomerCommandResult,
    customer_snapshot,
)
from erp.modules.customer.domain import Customer
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


def _audit_snapshot(customer: Customer) -> dict[str, object]:
    snapshot = customer_snapshot(customer)
    snapshot.pop("identity_value")
    return snapshot


class CustomerEffects:
    async def record(
        self,
        session: AsyncSession,
        customer: Customer,
        *,
        actor_id: UUID,
        metadata: CommandMetadata,
        event_type: str,
        payload: dict[str, object],
        before: Customer | None = None,
    ) -> CustomerCommandResult:
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=customer.company_id,
                branch_id=None,
                module="crm",
                entity_type="customer",
                entity_id=customer.id,
                operation=event_type,
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                source_ip=metadata.source_ip,
                before_snapshot=_audit_snapshot(before) if before is not None else None,
                after_snapshot=_audit_snapshot(customer),
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=event_type,
            event_version=1,
            producer_module="crm",
            producer_domain="customer",
            aggregate_type="customer",
            aggregate_id=customer.id,
            aggregate_version=customer.version,
            company_id=customer.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            request_id=metadata.request_id,
            causation_id=None,
            payload=payload,
        )
        await OutboxService().enqueue(session, envelope)
        return CustomerCommandResult(customer, envelope.message_id, audit_id)


__all__ = ["CustomerEffects"]
