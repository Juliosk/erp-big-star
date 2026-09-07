"""Golden-flow orchestration independent from framework and transport details."""

from erp.modules.platform_test.application.dto import (
    CreateTestEntityCommand,
    CreateTestEntityResult,
)
from erp.modules.platform_test.application.ports import (
    TestEntityEventTransport,
    TestEntityPersistence,
)


class TestEntityDeliveryTimeoutError(RuntimeError):
    """Raised when the expected event is not observed within the request budget."""


class CreateTestEntityService:
    """Coordinate durable create, publish, consume, audit and response replay."""

    def __init__(
        self,
        *,
        persistence: TestEntityPersistence,
        transport: TestEntityEventTransport,
        delivery_timeout_seconds: float = 5.0,
        max_deliveries: int = 100,
    ) -> None:
        self._persistence = persistence
        self._transport = transport
        self._delivery_timeout_seconds = delivery_timeout_seconds
        self._max_deliveries = max_deliveries

    async def execute(self, command: CreateTestEntityCommand) -> CreateTestEntityResult:
        """Run the disposable Sprint 1 acceptance scenario end to end."""
        creation = await self._persistence.create(command)
        if creation.replayed_response is not None:
            return CreateTestEntityResult.from_replay(creation.replayed_response)
        if (
            creation.entity_id is None
            or creation.event_id is None
            or creation.audit_event_id is None
        ):
            raise RuntimeError("New creation did not return its durable identifiers.")

        await self._transport.publish(creation.event_id)
        for _ in range(self._max_deliveries):
            delivery = await self._transport.receive(timeout_seconds=self._delivery_timeout_seconds)
            if delivery is None:
                break
            processing = await self._persistence.consume(delivery.envelope)
            is_expected = delivery.envelope.message_id == creation.event_id
            if is_expected:
                result = CreateTestEntityResult(
                    id=processing.entity_id,
                    name=processing.name,
                    status=processing.status,
                    version=processing.version,
                    event_id=creation.event_id,
                    audit_event_ids=(creation.audit_event_id, processing.audit_event_id),
                    idempotency_replayed=False,
                )
                await self._persistence.complete_idempotency(
                    record_id=creation.idempotency_record_id,
                    response_body=result.to_dict(),
                )
                await delivery.ack()
                return result
            await delivery.ack()

        raise TestEntityDeliveryTimeoutError


__all__ = ["CreateTestEntityService", "TestEntityDeliveryTimeoutError"]
