"""Ports isolating workflow orchestration from PostgreSQL and RabbitMQ."""

from typing import Protocol
from uuid import UUID

from erp.modules.platform_test.application.dto import (
    CreateTestEntityCommand,
    TestEntityCreation,
    TestEntityProcessing,
)
from erp.platform.messaging import MessageEnvelope


class TestEntityDelivery(Protocol):
    """Transport-neutral message that can be acknowledged after durable work."""

    @property
    def envelope(self) -> MessageEnvelope:
        """Return the validated corporate envelope."""
        ...

    async def ack(self) -> None:
        """Acknowledge the broker delivery."""
        ...


class TestEntityEventTransport(Protocol):
    """Capabilities required from the event transport adapter."""

    async def publish(self, event_id: UUID) -> None:
        """Publish one committed Outbox event."""
        ...

    async def receive(self, *, timeout_seconds: float) -> TestEntityDelivery | None:
        """Receive one event from this consumer's isolated queue."""
        ...


class TestEntityPersistence(Protocol):
    """Transactional persistence stages required by the workflow."""

    async def create(self, command: CreateTestEntityCommand) -> TestEntityCreation:
        """Commit entity, audit, Outbox and idempotency claim atomically."""
        ...

    async def consume(self, envelope: MessageEnvelope) -> TestEntityProcessing:
        """Commit Inbox, state transition and consumer audit atomically."""
        ...

    async def complete_idempotency(
        self,
        *,
        record_id: UUID,
        response_body: dict[str, object],
    ) -> None:
        """Persist the final public response for exact replay."""
        ...


__all__ = ["TestEntityDelivery", "TestEntityEventTransport", "TestEntityPersistence"]
