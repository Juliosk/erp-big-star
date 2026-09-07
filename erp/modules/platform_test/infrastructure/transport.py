"""RabbitMQ/Outbox transport adapter for the acceptance workflow."""

from dataclasses import dataclass
from uuid import UUID

from erp.modules.platform_test.application import TestEntityDelivery, TestEntityEventTransport
from erp.modules.platform_test.infrastructure.persistence import (
    TEST_ENTITY_CONSUMER,
    TEST_ENTITY_ROUTING_KEY,
)
from erp.platform.database import Database
from erp.platform.messaging import (
    BrokerPublishError,
    ConsumerBinding,
    IncomingDelivery,
    MessageEnvelope,
    RabbitMQBroker,
)
from erp.platform.outbox import OutboxPublisher


@dataclass(slots=True)
class RabbitTestEntityDelivery(TestEntityDelivery):
    """Application-facing wrapper around one aio-pika delivery."""

    _delivery: IncomingDelivery

    @property
    def envelope(self) -> MessageEnvelope:
        return self._delivery.envelope

    async def ack(self) -> None:
        await self._delivery.ack()


class RabbitTestEntityTransport(TestEntityEventTransport):
    """Declare the isolated consumer and bridge committed Outbox events."""

    BINDING = ConsumerBinding(
        consumer_name=TEST_ENTITY_CONSUMER,
        queue_name="erp.platform.test-entity-projector.v1",
        routing_key=TEST_ENTITY_ROUTING_KEY,
    )

    def __init__(self, database: Database, broker: RabbitMQBroker) -> None:
        self._database = database
        self._broker = broker

    async def publish(self, event_id: UUID) -> None:
        """Declare before mandatory publish, then finalize the Outbox record."""
        await self._broker.declare_consumer(self.BINDING)
        async with self._database.session() as session, session.begin():
            result = await OutboxPublisher(self._broker).publish_event(session, event_id)
        if result.failed or result.published != 1:
            raise BrokerPublishError("Expected Outbox event was not published.")

    async def receive(self, *, timeout_seconds: float) -> TestEntityDelivery | None:
        """Receive and validate only the version/type owned by this consumer."""
        delivery = await self._broker.get(self.BINDING, timeout_seconds=timeout_seconds)
        if delivery is None:
            return None
        envelope = delivery.envelope
        if (
            envelope.message_type != "TestEntityCreated"
            or envelope.event_version != 1
            or envelope.aggregate_type != "test_entity"
        ):
            await self._broker.retry_or_dead_letter(
                delivery,
                self.BINDING,
                error_code="SCHEMA_VALIDATION_FAILED",
                error_summary="Unsupported platform test event.",
            )
            return None
        return RabbitTestEntityDelivery(delivery)


__all__ = ["RabbitTestEntityDelivery", "RabbitTestEntityTransport"]
