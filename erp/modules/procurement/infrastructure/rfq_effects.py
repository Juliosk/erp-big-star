"""PostgreSQL Audit/Outbox adapter for governed RFQ mutations."""

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.application.purchasing import ProcurementCommandMetadata
from erp.modules.procurement.domain import RequestForQuotation
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


class PostgresRequestForQuotationEffects:
    """Stage RFQ audit and domain events without owning commit or rollback."""

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
        before: RequestForQuotation,
        after: RequestForQuotation,
        event_type: str,
        actor_id: UUID,
        metadata: ProcurementCommandMetadata,
    ) -> tuple[UUID, UUID]:
        audit_id = await self._audit.record(
            self._session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=after.company_id,
                branch_id=None,
                module="procurement",
                entity_type="request_for_quotation",
                entity_id=after.id,
                operation=event_type,
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                source_ip=metadata.source_ip,
                before_snapshot=rfq_snapshot(before),
                after_snapshot=rfq_snapshot(after),
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=event_type,
            event_version=1,
            producer_module="procurement",
            producer_domain="procurement",
            aggregate_type="request_for_quotation",
            aggregate_id=after.id,
            aggregate_version=after.version,
            company_id=after.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            causation_id=None,
            request_id=metadata.request_id,
            payload=rfq_snapshot(after),
        )
        await self._outbox.enqueue(self._session, envelope)
        return envelope.message_id, audit_id


def rfq_snapshot(rfq: RequestForQuotation) -> dict[str, object]:
    return {
        "id": str(rfq.id),
        "company_id": str(rfq.company_id),
        "code": rfq.code,
        "status": rfq.status.value,
        "created_by": str(rfq.created_by),
        "response_deadline": rfq.response_deadline.isoformat(),
        "item_count": len(rfq.items),
        "invited_supplier_ids": [str(value) for value in rfq.invited_supplier_ids],
        "quote_ids": [str(quote.id) for quote in rfq.supplier_quotes],
        "opened_at": None if rfq.opened_at is None else rfq.opened_at.isoformat(),
        "closed_at": None if rfq.closed_at is None else rfq.closed_at.isoformat(),
        "award": (
            None
            if rfq.award is None
            else {
                "quote_id": str(rfq.award.quote_id),
                "supplier_id": str(rfq.award.supplier_id),
                "awarded_by": str(rfq.award.awarded_by),
                "awarded_at": rfq.award.awarded_at.isoformat(),
            }
        ),
        "cancellation_reason": rfq.cancellation_reason,
        "version": rfq.version,
    }


__all__ = ["PostgresRequestForQuotationEffects", "rfq_snapshot"]
