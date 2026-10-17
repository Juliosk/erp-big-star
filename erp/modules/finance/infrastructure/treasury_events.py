"""Transactional Outbox adapter for M12 treasury events."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application.treasury import (
    PaymentBatchEvent,
    TreasuryCommandMetadata,
)
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


class PostgresPaymentBatchEventPublisher:
    """Stage payment-batch events without owning the database transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(
        self,
        event: PaymentBatchEvent,
        *,
        metadata: TreasuryCommandMetadata,
    ) -> UUID:
        batch = event.aggregate
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=event.event_type,
            event_version=1,
            producer_module="finance",
            producer_domain="treasury",
            aggregate_type="payment_batch",
            aggregate_id=batch.id,
            aggregate_version=batch.version,
            company_id=batch.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            causation_id=None,
            request_id=metadata.request_id,
            payload=event.payload,
        )
        await OutboxService().enqueue(self._session, envelope)
        return envelope.message_id


__all__ = ["PostgresPaymentBatchEventPublisher"]
