"""M23 lifecycle events cross real RabbitMQ and the idempotent Inbox.

Publish only this fixture's event IDs; never drain the application's pending Outbox.
"""

from uuid import UUID, uuid4

import aio_pika
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.config import get_settings
from erp.platform.inbox import InboxEventModel, InboxService
from erp.platform.messaging import MessageEnvelope, RabbitMQBroker
from erp.platform.outbox import OutboxEventModel
from erp.platform.outbox.publisher import OutboxPublisher
from tests.integration.import_api_support import command, import_api, upload

pytestmark = pytest.mark.integration


def test_import_events_transport_and_duplicate_delivery() -> None:
    with import_api() as fixture:
        job = upload(fixture, [["EVENT", uuid4().hex, "Transport probe", "PA", "UN"]])
        for action in ("validate", "preview", "confirm", "commit"):
            job = command(fixture, job, action)

        async def transport() -> None:
            settings = get_settings()
            consumer = f"m23-contract-test-{uuid4().hex}"
            broker = RabbitMQBroker(settings)
            received: list[MessageEnvelope] = []
            async with fixture.data.database.session() as session:
                events = list(
                    await session.scalars(
                        select(OutboxEventModel)
                        .where(
                            OutboxEventModel.source_module == "governance",
                            OutboxEventModel.aggregate_id == UUID(job["id"]),
                        )
                        .order_by(OutboxEventModel.occurred_at)
                    )
                )
            assert [event.event_type for event in events] == [
                "ImportJobCreated",
                "ImportValidationCompleted",
                "ImportPreviewReady",
                "ImportJobConfirmed",
                "ImportCommitted",
            ]

            async def effect(session: AsyncSession, envelope: MessageEnvelope) -> None:
                assert session.in_transaction()
                assert envelope.company_id == fixture.data.company_id
                assert envelope.producer_module == "governance"
                assert envelope.producer_domain == "data"
                assert envelope.event_version == 1
                assert envelope.payload["import_job_id"] == job["id"]
                received.append(envelope)

            try:
                await broker.connect()
                connection = await aio_pika.connect_robust(
                    host=settings.rabbitmq_host,
                    port=settings.rabbitmq_amqp_port,
                    login=settings.rabbitmq_default_user,
                    password=settings.rabbitmq_default_pass.get_secret_value(),
                    virtualhost=settings.rabbitmq_virtual_host,
                )
                async with connection:
                    channel = await connection.channel()
                    queue = await channel.declare_queue(consumer, exclusive=True, auto_delete=True)
                    exchange = await channel.get_exchange(settings.rabbitmq_events_exchange)
                    await queue.bind(exchange, routing_key="data.import-job.*.v1")
                    publisher = OutboxPublisher(broker)
                    for event in events:
                        async with fixture.data.database.session() as session, session.begin():
                            result = await publisher.publish_event(session, event.event_id)
                            assert result.published == 1
                            assert result.failed == 0
                        async with fixture.data.database.session() as session, session.begin():
                            assert (
                                await publisher.publish_event(session, event.event_id)
                            ).published == 0
                        delivery = await queue.get(timeout=5)
                        assert delivery is not None
                        envelope = MessageEnvelope.model_validate_json(delivery.body)
                        assert envelope.message_id == event.event_id
                        assert envelope.message_type == event.event_type
                        for duplicate in (False, True):
                            async with fixture.data.database.session() as session, session.begin():
                                processed = await InboxService().process(
                                    session,
                                    consumer_name=consumer,
                                    envelope=envelope,
                                    effect=effect,
                                )
                                assert processed.duplicate is duplicate
                                assert processed.processed is not duplicate
                        await delivery.ack()
                    assert [event.aggregate_version for event in received] == [1, 2, 3, 4, 5]
                    assert received[-1].payload["count"] == 1
                    assert received[-1].payload["affected_domain"] == "product"
            finally:
                await broker.close()
                async with fixture.data.database.session() as session, session.begin():
                    await session.execute(
                        delete(InboxEventModel).where(InboxEventModel.consumer_name == consumer)
                    )

        assert fixture.client.portal is not None
        fixture.client.portal.call(transport)
