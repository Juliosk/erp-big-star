"""RabbitMQ transport for the first M1 corporate projection."""

from typing import ClassVar
from uuid import UUID

from erp.modules.admin.infrastructure.corporate_events import (
    BRANCH_CREATED,
    BRANCH_CREATED_ROUTING_KEY,
    BRANCH_UPDATED,
    BRANCH_UPDATED_ROUTING_KEY,
    COMPANY_CREATED,
    COMPANY_CREATED_ROUTING_KEY,
    COMPANY_UPDATED,
    COMPANY_UPDATED_ROUTING_KEY,
)
from erp.platform.database import Database
from erp.platform.messaging import (
    BrokerPublishError,
    ConsumerBinding,
    IncomingDelivery,
    RabbitMQBroker,
)
from erp.platform.outbox import OutboxPublisher


class RabbitCorporateEventTransport:
    """Declare isolated bindings and bridge committed M1 Outbox events."""

    BINDINGS: ClassVar[dict[str, ConsumerBinding]] = {
        COMPANY_CREATED: ConsumerBinding(
            consumer_name="admin-corporate-projector",
            queue_name="erp.admin.corporate-projector.company-created.v1",
            routing_key=COMPANY_CREATED_ROUTING_KEY,
        ),
        COMPANY_UPDATED: ConsumerBinding(
            consumer_name="admin-corporate-projector",
            queue_name="erp.admin.corporate-projector.company-updated.v1",
            routing_key=COMPANY_UPDATED_ROUTING_KEY,
        ),
        BRANCH_CREATED: ConsumerBinding(
            consumer_name="admin-corporate-projector",
            queue_name="erp.admin.corporate-projector.branch-created.v1",
            routing_key=BRANCH_CREATED_ROUTING_KEY,
        ),
        BRANCH_UPDATED: ConsumerBinding(
            consumer_name="admin-corporate-projector",
            queue_name="erp.admin.corporate-projector.branch-updated.v1",
            routing_key=BRANCH_UPDATED_ROUTING_KEY,
        ),
    }

    def __init__(self, database: Database, broker: RabbitMQBroker) -> None:
        self._database = database
        self._broker = broker

    async def publish(self, event_id: UUID) -> None:
        for binding in self.BINDINGS.values():
            await self._broker.declare_consumer(binding)
        async with self._database.session() as session, session.begin():
            result = await OutboxPublisher(self._broker).publish_event(session, event_id)
        if result.failed or result.published != 1:
            raise BrokerPublishError("Expected corporate Outbox event was not published.")

    async def receive(
        self,
        message_type: str,
        *,
        timeout_seconds: float = 5.0,
    ) -> IncomingDelivery | None:
        binding = self.BINDINGS.get(message_type)
        if binding is None:
            raise ValueError("Unsupported corporate event type.")
        delivery = await self._broker.get(binding, timeout_seconds=timeout_seconds)
        if delivery is None:
            return None
        envelope = delivery.envelope
        if envelope.message_type != message_type or envelope.event_version != 1:
            await self._broker.retry_or_dead_letter(
                delivery,
                binding,
                error_code="SCHEMA_VALIDATION_FAILED",
                error_summary="Unsupported corporate event envelope.",
            )
            return None
        return delivery

    async def purge(self) -> None:
        for binding in self.BINDINGS.values():
            await self._broker.purge_consumer(binding)


__all__ = ["RabbitCorporateEventTransport"]
