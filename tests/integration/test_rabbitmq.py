"""RabbitMQ integration coverage for durable topology and confirmed messages."""

import asyncio
from uuid import uuid4

import pytest

from erp.platform.config import get_settings
from erp.platform.messaging import (
    ConsumerBinding,
    MessageEnvelope,
    MessageKind,
    RabbitMQBroker,
    build_routing_key,
)


@pytest.mark.integration
def test_rabbitmq_publishes_and_consumes_corporate_envelope() -> None:
    async def scenario() -> None:
        settings = get_settings()
        broker = RabbitMQBroker(settings)
        suffix = uuid4().hex
        routing_key = build_routing_key(
            domain="platform",
            aggregate="test-entity",
            action=f"created-{suffix}",
            version=1,
        )
        binding = ConsumerBinding(
            consumer_name="platform-test",
            queue_name=f"erp.platform.test-{suffix}.v1",
            routing_key=routing_key,
        )
        identity = uuid4()
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type="TestEntityCreated",
            event_version=1,
            producer_module="platform",
            producer_domain="platform",
            aggregate_type="test_entity",
            aggregate_id=identity,
            aggregate_version=1,
            company_id=None,
            branch_id=None,
            correlation_id=identity,
            causation_id=None,
            request_id=identity,
            payload={"name": "broker-confirmed"},
        )
        try:
            await broker.declare_consumer(binding)
            await broker.publish(envelope, routing_key=routing_key)
            delivery = await broker.get(binding, timeout_seconds=2.0)

            assert delivery is not None
            assert delivery.envelope == envelope
            assert delivery.routing_key == routing_key
            await delivery.ack()
            await broker.purge_consumer(binding)
        finally:
            await broker.close()

    asyncio.run(scenario())


@pytest.mark.integration
def test_rabbitmq_exhausts_four_retries_before_isolated_dlq() -> None:
    async def scenario() -> None:
        settings = get_settings().model_copy(update={"rabbitmq_retry_delays_ms": (10, 10, 10, 10)})
        broker = RabbitMQBroker(settings)
        suffix = uuid4().hex
        routing_key = build_routing_key(
            domain="platform",
            aggregate="test-entity",
            action=f"failed-{suffix}",
            version=1,
        )
        binding = ConsumerBinding(
            consumer_name="platform-retry-test",
            queue_name=f"erp.platform.retry-test-{suffix}.v1",
            routing_key=routing_key,
        )
        identity = uuid4()
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type="TestEntityFailed",
            event_version=1,
            producer_module="platform",
            producer_domain="platform",
            aggregate_type="test_entity",
            aggregate_id=identity,
            aggregate_version=1,
            company_id=None,
            branch_id=None,
            correlation_id=identity,
            causation_id=None,
            request_id=identity,
            payload={"name": "retry"},
        )
        try:
            await broker.declare_consumer(binding)
            await broker.publish(envelope, routing_key=routing_key)
            dead_lettered = False
            for attempt in range(1, 6):
                delivery = await broker.get(binding, timeout_seconds=2.0)
                assert delivery is not None
                dead_lettered = await broker.retry_or_dead_letter(
                    delivery,
                    binding,
                    error_code="TRANSIENT_FAILURE",
                    error_summary="retry integration test",
                )
                assert dead_lettered is (attempt == 5)
                if not dead_lettered:
                    await asyncio.sleep(0.05)

            dead_letter = await broker.get_dead_letter(binding, timeout_seconds=2.0)
            assert dead_letter is not None
            assert dead_letter.envelope.message_id == envelope.message_id
            assert dead_letter.headers["retry_attempt"] == 5
            assert dead_letter.headers["original_routing_key"] == routing_key
            await dead_letter.ack()
            await broker.purge_consumer(binding)
        finally:
            await broker.close()

    asyncio.run(scenario())
