"""M2 HTTP -> confirmed Outbox publisher -> real RabbitMQ -> idempotent Inbox.

The test consumer is a contract probe, not an invented M3/M10 business projection.
Only exact fixture events are published. Its exclusive queue disappears on disconnect.
"""

from dataclasses import replace
from uuid import UUID, uuid4

import aio_pika
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.product.application.permissions import PRODUCT_ACTIVATE, PRODUCT_DISCONTINUE
from erp.platform.config import get_settings
from erp.platform.inbox import InboxEventModel, InboxService
from erp.platform.messaging import MessageEnvelope, RabbitMQBroker
from erp.platform.outbox import OutboxEventModel
from erp.platform.outbox.publisher import OutboxPublisher
from tests.integration.product_api_support import product_api
from tests.integration.test_product_creation_api import allow_create, creation_body

pytestmark = pytest.mark.integration


def test_product_event_catalog_survives_transport_and_duplicate_delivery() -> None:
    with product_api() as api:
        allow_create(api)
        created = api.client.post(
            "/api/v1/products",
            json=creation_body(api),
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert created.status_code == 201
        events = [("ProductCreated", UUID(created.json()["event_id"]))]
        url = created.headers["location"]
        path, query = url.split("?")
        assert api.resolver.context is not None
        from erp.modules.product.application.permissions import PRODUCT_UPDATE

        api.resolver.context = replace(
            api.resolver.context,
            permissions=api.resolver.context.permissions
            | {PRODUCT_UPDATE, PRODUCT_ACTIVATE, PRODUCT_DISCONTINUE},
        )
        for version, action, message_type in (
            (1, "barcodes", "ProductBarcodeChanged"),
            (2, "submit-for-homologation", "ProductUpdated"),
            (3, "activate", "ProductActivated"),
            (4, "discontinue", "ProductDiscontinued"),
        ):
            response = api.client.post(
                f"{path}/{action}?{query}",
                json={"barcode_type": "INTERNAL", "barcode": "E2E-0001"}
                if action == "barcodes"
                else None,
                headers={
                    **api.headers,
                    "If-Match": f'"{version}"',
                    "Idempotency-Key": str(uuid4()),
                },
            )
            assert response.status_code in (200, 201)
            events.append((message_type, UUID(response.json()["event_id"])))

        async def transport() -> None:
            settings = get_settings()
            consumer_name = f"m2-contract-test-{uuid4().hex}"
            broker = RabbitMQBroker(settings)
            received: list[MessageEnvelope] = []
            event_ids = [event_id for _, event_id in events]

            async def effect(session: AsyncSession, envelope: MessageEnvelope) -> None:
                assert envelope.company_id == api.data.company_id
                assert envelope.producer_module == "product"
                assert envelope.event_version == 1
                assert envelope.payload["product_id"] == created.json()["product"]["id"]
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
                    queue = await channel.declare_queue(
                        consumer_name, exclusive=True, auto_delete=True
                    )
                    exchange = await channel.get_exchange(settings.rabbitmq_events_exchange)
                    for action in ("created", "changed", "updated", "activated", "discontinued"):
                        await queue.bind(exchange, routing_key=f"product.product.{action}.v1")
                    publisher = OutboxPublisher(broker)
                    for expected_type, event_id in events:
                        async with api.data.database.session() as session, session.begin():
                            published = await publisher.publish_event(session, event_id)
                            assert published.published == 1
                            assert published.failed == 0
                        async with api.data.database.session() as session, session.begin():
                            assert (await publisher.publish_event(session, event_id)).published == 0
                        delivery = await queue.get(timeout=5)
                        assert delivery is not None
                        envelope = MessageEnvelope.model_validate_json(delivery.body)
                        assert envelope.message_id == event_id
                        assert envelope.message_type == expected_type
                        for duplicate in (False, True):
                            async with api.data.database.session() as session, session.begin():
                                result = await InboxService().process(
                                    session,
                                    consumer_name=consumer_name,
                                    envelope=envelope,
                                    effect=effect,
                                )
                                assert result.duplicate is duplicate
                                assert result.processed is not duplicate
                        await delivery.ack()
                    assert [event.message_type for event in received] == [
                        name for name, _ in events
                    ]
                    assert [event.aggregate_version for event in received] == list(range(1, 6))
                    async with api.data.database.session() as session:
                        inbox = (
                            await session.scalars(
                                select(InboxEventModel).where(
                                    InboxEventModel.consumer_name == consumer_name
                                )
                            )
                        ).all()
                        outbox = (
                            await session.scalars(
                                select(OutboxEventModel).where(
                                    OutboxEventModel.event_id.in_(event_ids)
                                )
                            )
                        ).all()
                        assert len(inbox) == len(outbox) == 5
                        assert all(item.processed_at is not None for item in inbox)
                        assert all(item.published_at is not None for item in outbox)
            finally:
                await broker.close()
                async with api.data.database.session() as session, session.begin():
                    await session.execute(
                        delete(InboxEventModel).where(
                            InboxEventModel.consumer_name == consumer_name
                        )
                    )

        assert api.client.portal is not None
        api.client.portal.call(transport)
