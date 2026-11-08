"""Production Outbox publishers and resilient cross-module Inbox consumers."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, func, inspect, select

from erp.modules.production.application import (
    ProductionDomainEvent,
    ProductionEventType,
)
from erp.modules.production.infrastructure import (
    PRODUCTION_EVENT_CONSUMER,
    PRODUCTION_SYNCHRONIZATION_REQUESTED,
    ProductionEventConsumer,
    ProductionSourceCursorModel,
    ProductionSynchronizationRequestModel,
    ProductionSynchronizationWorker,
    TransactionalProductionEventPublisher,
    accept_production_source_cursor,
    enqueue_production_synchronizations,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.inbox import InboxEventModel, InboxStatus
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_planned_order_conversion import (
    ConversionFixture,
    _command,
    _conversion_service,
    conversion_fixture,
)

pytestmark = pytest.mark.integration

OCCURRED_AT = datetime(2026, 11, 8, 12, tzinfo=UTC)


@asynccontextmanager
async def production_event_fixture() -> AsyncIterator[ConversionFixture]:
    async with conversion_fixture() as data:
        companies = (data.production.company_id, data.production.other_company_id)
        try:
            yield data
        finally:
            async with data.production.database.session() as session, session.begin():
                await session.execute(
                    delete(ProductionSynchronizationRequestModel).where(
                        ProductionSynchronizationRequestModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(ProductionSourceCursorModel).where(
                        ProductionSourceCursorModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(InboxEventModel).where(
                        InboxEventModel.consumer_name == PRODUCTION_EVENT_CONSUMER
                    )
                )


async def _convert(data: ConversionFixture) -> UUID:
    async with data.production.database.session() as session, session.begin():
        result = await _conversion_service(data, session).convert(
            _command(data, data.manufacture_order_id),
            actor_id=data.production.actor_id,
        )
        return result.production_order.id


def _inventory_event(
    data: ConversionFixture,
    *,
    aggregate_id: UUID | None = None,
    aggregate_version: int = 1,
    occurred_at: datetime = OCCURRED_AT,
    payload_company_id: UUID | None = None,
) -> MessageEnvelope:
    return MessageEnvelope(
        message_id=uuid4(),
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type="InventoryAdjusted",
        event_version=1,
        producer_module="inventory",
        producer_domain="inventory",
        aggregate_type="inventory_adjustment",
        aggregate_id=aggregate_id or uuid4(),
        aggregate_version=aggregate_version,
        company_id=data.production.company_id,
        branch_id=None,
        occurred_at=occurred_at,
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        payload={
            "company_id": str(payload_company_id or data.production.company_id),
            "postings": [
                {
                    "product_id": str(data.production.raw_material.id),
                    "quantity_delta": "1",
                }
            ],
        },
    )


def test_transactional_publisher_stages_all_required_production_events() -> None:
    async def scenario() -> None:
        async with production_event_fixture() as data:
            order_id = await _convert(data)
            request_id = uuid4()
            correlation_id = uuid4()
            async with data.production.database.session() as session, session.begin():
                publisher = TransactionalProductionEventPublisher(session)
                for event_type in ProductionEventType:
                    await publisher.publish(
                        ProductionDomainEvent(
                            event_type=event_type,
                            company_id=data.production.company_id,
                            production_order_id=order_id,
                            aggregate_version=1,
                            occurred_at=OCCURRED_AT,
                            request_id=request_id,
                            correlation_id=correlation_id,
                            causation_id=None,
                            payload={"source": "integration-test"},
                        )
                    )
            async with data.production.database.session() as session:
                event_types = set(
                    await session.scalars(
                        select(OutboxEventModel.event_type).where(
                            OutboxEventModel.aggregate_id == order_id,
                            OutboxEventModel.event_type.in_(
                                tuple(value.value for value in ProductionEventType)
                            ),
                        )
                    )
                )
                assert event_types == {value.value for value in ProductionEventType}

    asyncio.run(scenario())


def test_inventory_event_is_consumed_once_and_requests_order_synchronization() -> None:
    async def scenario() -> None:
        async with production_event_fixture() as data:
            order_id = await _convert(data)
            event = _inventory_event(data)
            consumer = ProductionEventConsumer(data.production.database)
            assert (await consumer.consume(event)).processed is True
            assert (await consumer.consume(event)).duplicate is True
            async with data.production.database.session() as session:
                outgoing = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_type
                        == PRODUCTION_SYNCHRONIZATION_REQUESTED,
                        OutboxEventModel.aggregate_id == order_id,
                        OutboxEventModel.causation_id == event.message_id,
                    )
                )
                assert outgoing is not None
                assert outgoing.payload["payload"]["reason"] == "STOCK_CHANGED"
                assert outgoing.payload["payload"]["affected_product_ids"] == [
                    str(data.production.raw_material.id)
                ]
                assert await session.get(
                    ProductionSynchronizationRequestModel,
                    (data.production.company_id, order_id),
                ) is None

    asyncio.run(scenario())


def test_monotonic_cursor_ignores_stale_event_and_inbox_records_delivery() -> None:
    async def scenario() -> None:
        async with production_event_fixture() as data:
            order_id = await _convert(data)
            aggregate_id = uuid4()
            latest = _inventory_event(
                data,
                aggregate_id=aggregate_id,
                aggregate_version=3,
                occurred_at=datetime(2026, 11, 8, 13, tzinfo=UTC),
            )
            stale = _inventory_event(
                data,
                aggregate_id=aggregate_id,
                aggregate_version=2,
                occurred_at=datetime(2026, 11, 8, 14, tzinfo=UTC),
            )
            consumer = ProductionEventConsumer(data.production.database)
            assert (await consumer.consume(latest)).processed
            assert (await consumer.consume(stale)).processed
            async with data.production.database.session() as session:
                cursor = await session.get(
                    ProductionSourceCursorModel,
                    (
                        data.production.company_id,
                        "inventory",
                        "inventory_adjustment",
                        aggregate_id,
                    ),
                )
                assert cursor is not None
                assert cursor.aggregate_version == 3
                assert await session.scalar(
                    select(func.count())
                    .select_from(InboxEventModel)
                    .where(
                        InboxEventModel.consumer_name == PRODUCTION_EVENT_CONSUMER,
                        InboxEventModel.status == InboxStatus.PROCESSED,
                    )
                ) == 2
                assert await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(
                        OutboxEventModel.event_type
                        == PRODUCTION_SYNCHRONIZATION_REQUESTED,
                        OutboxEventModel.aggregate_id == order_id,
                    )
                ) == 1

    asyncio.run(scenario())


def test_skip_locked_keeps_durable_work_for_later_worker() -> None:
    async def scenario() -> None:
        async with production_event_fixture() as data:
            order_id = await _convert(data)
            event = _inventory_event(data)
            async with data.production.database.session() as session, session.begin():
                assert await accept_production_source_cursor(session, event)
                assert await enqueue_production_synchronizations(
                    session,
                    event,
                    requested_at=OCCURRED_AT,
                ) == (order_id,)

            async with data.production.database.session() as locking_session:
                transaction = await locking_session.begin()
                await locking_session.scalar(
                    select(ProductionSynchronizationRequestModel)
                    .where(
                        ProductionSynchronizationRequestModel.company_id
                        == data.production.company_id,
                        ProductionSynchronizationRequestModel.production_order_id
                        == order_id,
                    )
                    .with_for_update()
                )
                async with (
                    data.production.database.session() as worker_session,
                    worker_session.begin(),
                ):
                    assert await ProductionSynchronizationWorker().run_pending(
                        worker_session,
                        company_id=data.production.company_id,
                    ) == ()
                await transaction.commit()

            async with data.production.database.session() as session, session.begin():
                assert await ProductionSynchronizationWorker().run_pending(
                    session,
                    company_id=data.production.company_id,
                ) == (order_id,)

    asyncio.run(scenario())


def test_consumer_rejects_cross_tenant_payload_before_inbox() -> None:
    async def scenario() -> None:
        async with production_event_fixture() as data:
            event = _inventory_event(
                data,
                payload_company_id=data.production.other_company_id,
            )
            with pytest.raises(ValueError, match="company boundary"):
                await ProductionEventConsumer(data.production.database).consume(event)
            async with data.production.database.session() as session:
                assert await session.scalar(
                    select(func.count())
                    .select_from(InboxEventModel)
                    .where(InboxEventModel.consumer_name == PRODUCTION_EVENT_CONSUMER)
                ) == 0

    asyncio.run(scenario())


def test_migration_0056_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    tables = set(
                        inspect(sync_connection).get_table_names(schema="production")
                    )
                    event_tables = {
                        "production_source_cursor",
                        "production_synchronization_request",
                    }
                    assert event_tables.issubset(tables) is expected

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0055")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0056")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")


__all__: list[str] = []
