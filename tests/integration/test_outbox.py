"""PostgreSQL integration coverage for Transactional Outbox atomicity."""

import asyncio
from uuid import uuid4

import pytest

from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxRepository, OutboxService


def envelope() -> MessageEnvelope:
    identity = uuid4()
    return MessageEnvelope.new(
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
        payload={"name": "transactional"},
    )


@pytest.mark.integration
def test_outbox_event_commits_with_caller_transaction() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        event = envelope()
        try:
            async with database.session() as session, session.begin():
                await OutboxService().enqueue(session, event)

            async with database.session() as session:
                stored = await OutboxRepository().get_by_event_id(session, event.message_id)

            assert stored is not None
            assert stored.payload["message_id"] == str(event.message_id)
            assert stored.published_at is None
            assert stored.publish_attempts == 0
        finally:
            await database.dispose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_outbox_event_rolls_back_with_caller_transaction() -> None:
    class RollbackMarker(Exception):
        pass

    async def scenario() -> None:
        database = Database(get_settings())
        event = envelope()

        async def enqueue_then_rollback() -> None:
            async with database.session() as session, session.begin():
                await OutboxService().enqueue(session, event)
                raise RollbackMarker

        try:
            with pytest.raises(RollbackMarker):
                await enqueue_then_rollback()

            async with database.session() as session:
                stored = await OutboxRepository().get_by_event_id(session, event.message_id)

            assert stored is None
        finally:
            await database.dispose()

    asyncio.run(scenario())
