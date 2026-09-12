"""M5 adjustment events cross real RabbitMQ and the idempotent Inbox."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from erp.modules.inventory.infrastructure import (
    INVENTORY_MOVEMENT_PROJECTOR,
    InventoryMovementProjectionConsumer,
    InventoryMovementProjectionModel,
    RabbitInventoryMovementTransport,
)
from erp.platform.config import get_settings
from erp.platform.inbox import InboxEventModel, InboxStatus
from erp.platform.messaging import RabbitMQBroker
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_inventory_adjustments_api import (
    _adjustment_body,
    _allow_adjustment,
    _seed_lot_dimensions,
)
from tests.integration.test_inventory_api import inventory_api

pytestmark = pytest.mark.integration


def test_inventory_adjusted_event_projects_once_through_rabbitmq_inbox() -> None:
    with inventory_api() as api:
        _allow_adjustment(api)
        product_id, warehouse_id, lot_id = _seed_lot_dimensions(api)
        body = _adjustment_body(api, product_id=product_id, warehouse_id=warehouse_id)
        body["lines"][0]["lot_id"] = lot_id
        adjusted = api.client.post(
            "/api/v1/inventory/adjustments",
            json=body,
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert adjusted.status_code == 201
        event_id = UUID(adjusted.json()["event_id"])

        async def transport() -> None:
            settings = get_settings()
            broker = RabbitMQBroker(settings)
            projector = InventoryMovementProjectionConsumer(api.data.database)
            movement_transport = RabbitInventoryMovementTransport(api.data.database, broker)
            try:
                await broker.connect()
                await movement_transport.purge()
                await movement_transport.publish(event_id)
                delivery = await movement_transport.receive(timeout_seconds=5)
                assert delivery is not None
                envelope = delivery.envelope
                assert envelope.message_id == event_id
                assert envelope.message_type == "InventoryAdjusted"
                assert envelope.company_id == api.data.company_id
                assert envelope.payload["reason"] == "Initial inventory count"
                assert envelope.payload["postings"][0]["lot_id"] == lot_id
                first = await projector.consume(envelope)
                duplicate = await projector.consume(envelope)
                await delivery.ack()
                assert first.processed is True
                assert first.duplicate is False
                assert duplicate.processed is False
                assert duplicate.duplicate is True

                async with api.data.database.session() as session:
                    projection = await session.get(InventoryMovementProjectionModel, event_id)
                    inbox = await session.scalar(
                        select(InboxEventModel).where(
                            InboxEventModel.consumer_name == INVENTORY_MOVEMENT_PROJECTOR,
                            InboxEventModel.event_id == event_id,
                        )
                    )
                    outbox = await session.scalar(
                        select(OutboxEventModel).where(OutboxEventModel.event_id == event_id)
                    )
                    assert projection is not None
                    assert projection.transaction_id == UUID(adjusted.json()["transaction_id"])
                    assert projection.company_id == api.data.company_id
                    assert projection.posting_count == 1
                    assert inbox is not None
                    assert inbox.status == InboxStatus.PROCESSED
                    assert inbox.processed_at is not None
                    assert inbox.attempts == 2
                    assert outbox is not None
                    assert outbox.published_at is not None
            finally:
                await broker.close()
                async with api.data.database.session() as session, session.begin():
                    await session.execute(
                        delete(InboxEventModel).where(
                            InboxEventModel.consumer_name == INVENTORY_MOVEMENT_PROJECTOR
                        )
                    )
                    await session.execute(
                        delete(InventoryMovementProjectionModel).where(
                            InventoryMovementProjectionModel.event_id == event_id
                        )
                    )

        assert api.client.portal is not None
        api.client.portal.call(transport)
