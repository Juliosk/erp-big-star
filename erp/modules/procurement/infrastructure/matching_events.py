"""Transactional Outbox adapter for M6 matching execution events."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.application.matching import MatchingExecutionEvent
from erp.modules.procurement.application.purchasing import ProcurementCommandMetadata
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


class PostgresMatchingEventPublisher:
    """Stage matching envelopes without committing the caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(
        self,
        event: MatchingExecutionEvent,
        *,
        metadata: ProcurementCommandMetadata,
    ) -> UUID:
        aggregate = event.aggregate
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=event.event_type,
            event_version=1,
            producer_module="procurement",
            producer_domain="procurement",
            aggregate_type="three_way_match_session",
            aggregate_id=aggregate.id,
            aggregate_version=aggregate.version,
            company_id=aggregate.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            causation_id=None,
            request_id=metadata.request_id,
            payload=dict(event.payload),
        )
        await OutboxService().enqueue(self._session, envelope)
        return envelope.message_id


__all__ = ["PostgresMatchingEventPublisher"]
