"""PostgreSQL Audit/Outbox adapter for M12 payment-request governance."""

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application.treasury import TreasuryCommandMetadata
from erp.modules.finance.domain import PaymentRequest
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


class _AuditWriter(Protocol):
    async def record(self, session: AsyncSession, event: AuditEvent) -> UUID: ...


class _OutboxWriter(Protocol):
    async def enqueue(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
        *,
        headers: dict[str, Any] | None = None,
    ) -> UUID: ...


class PostgresPaymentRequestEffects:
    """Stage payment approval audit and events in the aggregate transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: _AuditWriter | None = None,
        outbox: _OutboxWriter | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService()
        self._outbox = outbox or OutboxService()

    async def record(
        self,
        *,
        before: PaymentRequest,
        after: PaymentRequest,
        event_type: str,
        actor_id: UUID,
        metadata: TreasuryCommandMetadata,
    ) -> tuple[UUID, UUID]:
        audit_id = await self._audit.record(
            self._session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=after.company_id,
                branch_id=None,
                module="finance",
                entity_type="payment_request",
                entity_id=after.id,
                operation=event_type,
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                source_ip=metadata.source_ip,
                before_snapshot=payment_request_snapshot(before),
                after_snapshot=payment_request_snapshot(after),
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=event_type,
            event_version=1,
            producer_module="finance",
            producer_domain="finance",
            aggregate_type="payment_request",
            aggregate_id=after.id,
            aggregate_version=after.version,
            company_id=after.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            causation_id=None,
            request_id=metadata.request_id,
            payload=payment_request_snapshot(after),
        )
        await self._outbox.enqueue(self._session, envelope)
        return envelope.message_id, audit_id


def payment_request_snapshot(request: PaymentRequest) -> dict[str, object]:
    return {
        "id": str(request.id),
        "company_id": str(request.company_id),
        "code": request.code,
        "treasury_account_id": str(request.treasury_account_id),
        "requested_by": str(request.requested_by),
        "requested_at": request.requested_at.isoformat(),
        "scheduled_on": request.scheduled_on.isoformat(),
        "purpose": request.purpose,
        "currency": request.currency,
        "total_amount": str(request.total_amount),
        "status": request.status.value,
        "workflow_instance_id": (
            None if request.workflow_instance_id is None else str(request.workflow_instance_id)
        ),
        "approved_by": (None if request.approved_by is None else str(request.approved_by)),
        "approved_at": (None if request.approved_at is None else request.approved_at.isoformat()),
        "batch_id": None if request.batch_id is None else str(request.batch_id),
        "transition_reason": request.transition_reason,
        "installment_ids": [str(item.installment_id) for item in request.items],
        "version": request.version,
    }


__all__ = ["PostgresPaymentRequestEffects", "payment_request_snapshot"]
