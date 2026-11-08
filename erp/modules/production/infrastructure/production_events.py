"""Transactional Production event publisher backed by the corporate Outbox."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.production.application.events import ProductionDomainEvent
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


class TransactionalProductionEventPublisher:
    """Stage Production facts without owning the database transaction."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        outbox: OutboxService | None = None,
    ) -> None:
        self._session = session
        self._outbox = outbox or OutboxService()

    async def publish(self, event: ProductionDomainEvent) -> UUID:
        payload = {
            **event.payload,
            "company_id": str(event.company_id),
            "production_order_id": str(event.production_order_id),
        }
        envelope = MessageEnvelope(
            message_id=uuid4(),
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=event.event_type.value,
            event_version=1,
            producer_module="production",
            producer_domain="production",
            aggregate_type="production_order",
            aggregate_id=event.production_order_id,
            aggregate_version=event.aggregate_version,
            company_id=event.company_id,
            branch_id=None,
            occurred_at=event.occurred_at,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            request_id=event.request_id,
            payload=payload,
        )
        return await self._outbox.enqueue(self._session, envelope)


__all__ = ["TransactionalProductionEventPublisher"]
