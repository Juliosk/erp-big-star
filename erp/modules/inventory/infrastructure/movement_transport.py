"""RabbitMQ transport for M5 movement projections."""

from typing import ClassVar
from uuid import UUID

from erp.modules.inventory.infrastructure.movement_projection import INVENTORY_ADJUSTED
from erp.platform.database import Database
from erp.platform.messaging import (
    BrokerPublishError,
    ConsumerBinding,
    IncomingDelivery,
    RabbitMQBroker,
    build_routing_key,
)
from erp.platform.outbox import OutboxPublisher

INVENTORY_ADJUSTED_ROUTING_KEY = build_routing_key(
    domain="inventory",
    aggregate="inventory-adjustment",
    action="adjusted",
    version=1,
)


class RabbitInventoryMovementTransport:
    """Declare isolated bindings and bridge committed M5 Outbox events."""

    BINDINGS: ClassVar[dict[str, ConsumerBinding]] = {
        INVENTORY_ADJUSTED: ConsumerBinding(
            consumer_name="inventory-movement-projector",
            queue_name="erp.inventory.movement-projector.adjusted.v1",
            routing_key=INVENTORY_ADJUSTED_ROUTING_KEY,
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
            raise BrokerPublishError("Expected inventory Outbox event was not published.")

    async def receive(
        self,
        message_type: str = INVENTORY_ADJUSTED,
        *,
        timeout_seconds: float = 5.0,
    ) -> IncomingDelivery | None:
        binding = self.BINDINGS.get(message_type)
        if binding is None:
            raise ValueError("Unsupported inventory event type.")
        delivery = await self._broker.get(binding, timeout_seconds=timeout_seconds)
        if delivery is None:
            return None
        envelope = delivery.envelope
        if (
            envelope.message_type != message_type
            or envelope.event_version != 1
            or envelope.aggregate_type != "inventory_adjustment"
        ):
            await self._broker.retry_or_dead_letter(
                delivery,
                binding,
                error_code="SCHEMA_VALIDATION_FAILED",
                error_summary="Unsupported inventory movement event envelope.",
            )
            return None
        return delivery

    async def purge(self) -> None:
        for binding in self.BINDINGS.values():
            await self._broker.purge_consumer(binding)


__all__ = ["INVENTORY_ADJUSTED_ROUTING_KEY", "RabbitInventoryMovementTransport"]
