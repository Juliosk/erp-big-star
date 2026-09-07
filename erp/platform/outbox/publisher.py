"""Outbox publisher coordinated with RabbitMQ confirms."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.messaging import MessageEnvelope, RabbitMQBroker, build_routing_key
from erp.platform.messaging.routing import action_from_message_type
from erp.platform.outbox.repository import OutboxRepository


@dataclass(frozen=True, slots=True)
class PublishBatchResult:
    """Observable result of one bounded Outbox publication pass."""

    published: int
    failed: int


class OutboxPublisher:
    """Claim pending events, publish them and record broker-confirmed outcomes."""

    def __init__(
        self,
        broker: RabbitMQBroker,
        repository: OutboxRepository | None = None,
    ) -> None:
        self._broker = broker
        self._repository = repository or OutboxRepository()

    async def publish_batch(self, session: AsyncSession, *, limit: int = 100) -> PublishBatchResult:
        """Publish one lock-protected batch inside the caller-owned transaction."""
        events = await self._repository.claim_pending(session, limit=limit)
        published = 0
        failed = 0
        for event in events:
            envelope = MessageEnvelope.model_validate(event.payload)
            routing_key = str(
                event.headers.get("routing_key")
                or build_routing_key(
                    domain=envelope.producer_domain,
                    aggregate=envelope.aggregate_type.replace("_", "-"),
                    action=action_from_message_type(envelope.message_type),
                    version=envelope.event_version,
                )
            )
            try:
                await self._broker.publish(
                    envelope,
                    routing_key=routing_key,
                    headers=event.headers,
                )
            except Exception as error:
                self._repository.mark_failed(event, error_summary=type(error).__name__)
                failed += 1
            else:
                self._repository.mark_published(event, published_at=datetime.now(UTC))
                published += 1
        await session.flush()
        return PublishBatchResult(published=published, failed=failed)

    async def publish_event(self, session: AsyncSession, event_id: UUID) -> PublishBatchResult:
        """Publish one deterministic pending event and record its confirmed outcome."""
        event = await self._repository.claim_by_event_id(session, event_id)
        if event is None:
            return PublishBatchResult(published=0, failed=0)
        envelope = MessageEnvelope.model_validate(event.payload)
        routing_key = str(
            event.headers.get("routing_key")
            or build_routing_key(
                domain=envelope.producer_domain,
                aggregate=envelope.aggregate_type.replace("_", "-"),
                action=action_from_message_type(envelope.message_type),
                version=envelope.event_version,
            )
        )
        try:
            await self._broker.publish(
                envelope,
                routing_key=routing_key,
                headers=event.headers,
            )
        except Exception as error:
            self._repository.mark_failed(event, error_summary=type(error).__name__)
            result = PublishBatchResult(published=0, failed=1)
        else:
            self._repository.mark_published(event, published_at=datetime.now(UTC))
            result = PublishBatchResult(published=1, failed=0)
        await session.flush()
        return result


__all__ = ["OutboxPublisher", "PublishBatchResult"]
