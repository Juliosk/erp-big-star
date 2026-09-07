"""PostgreSQL integration coverage for idempotent consumer transactions."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.audit import AuditEvent, AuditEventModel, AuditService
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.inbox import InboxRepository, InboxService, InboxStatus
from erp.platform.messaging import MessageEnvelope, MessageKind


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
        payload={"name": "idempotent"},
    )


async def audit_effect(session: AsyncSession, event: MessageEnvelope) -> None:
    await AuditService().record(
        session,
        AuditEvent(
            actor_user_id=None,
            company_id=None,
            branch_id=None,
            module="platform",
            entity_type=event.aggregate_type,
            entity_id=event.aggregate_id,
            operation="CONSUME",
            request_id=event.request_id,
            correlation_id=event.correlation_id,
            after_snapshot={"event_id": str(event.message_id)},
        ),
    )


@pytest.mark.integration
def test_inbox_executes_effect_once_and_records_duplicate_delivery() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        event = envelope()
        service = InboxService()
        consumer = f"test-consumer-{uuid4().hex}"
        try:
            async with database.session() as session, session.begin():
                first = await service.process(
                    session,
                    consumer_name=consumer,
                    envelope=event,
                    effect=audit_effect,
                )
            async with database.session() as session, session.begin():
                duplicate = await service.process(
                    session,
                    consumer_name=consumer,
                    envelope=event,
                    effect=audit_effect,
                )
            async with database.session() as session:
                stored = await InboxRepository().get(
                    session,
                    consumer_name=consumer,
                    event_id=event.message_id,
                )
                audit_count = await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(
                        AuditEventModel.entity_id == event.aggregate_id,
                        AuditEventModel.operation == "CONSUME",
                    )
                )

            assert first.processed is True
            assert duplicate.duplicate is True
            assert stored is not None
            assert stored.status == InboxStatus.PROCESSED
            assert stored.attempts == 2
            assert audit_count == 1
        finally:
            await database.dispose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_inbox_and_effect_both_roll_back_on_consumer_failure() -> None:
    class ConsumerFailure(Exception):
        pass

    async def scenario() -> None:
        database = Database(get_settings())
        event = envelope()
        consumer = f"rollback-consumer-{uuid4().hex}"

        async def failing_effect(session: AsyncSession, message: MessageEnvelope) -> None:
            await audit_effect(session, message)
            raise ConsumerFailure

        async def consume_then_fail() -> None:
            async with database.session() as session, session.begin():
                await InboxService().process(
                    session,
                    consumer_name=consumer,
                    envelope=event,
                    effect=failing_effect,
                )

        try:
            with pytest.raises(ConsumerFailure):
                await consume_then_fail()
            async with database.session() as session:
                stored = await InboxRepository().get(
                    session,
                    consumer_name=consumer,
                    event_id=event.message_id,
                )
                audit_count = await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(
                        AuditEventModel.entity_id == event.aggregate_id,
                        AuditEventModel.operation == "CONSUME",
                    )
                )

            assert stored is None
            assert audit_count == 0
        finally:
            await database.dispose()

    asyncio.run(scenario())
