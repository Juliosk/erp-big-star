"""Async matching event consumption against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, func, inspect, select

from erp.modules.procurement.infrastructure import (
    MATCHING_EVENT_CONSUMER,
    MATCHING_REEVALUATION_REQUESTED,
    MatchingEventConsumer,
    MatchingReevaluationModel,
    MatchingSourceCursorModel,
    ThreeWayMatchRepository,
    flag_matching_from_source_cursors,
)
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.inbox import InboxEventModel, InboxStatus
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_matching_repository import MatchingFixture, matching_fixture

pytestmark = pytest.mark.integration


@asynccontextmanager
async def matching_event_fixture(*, persisted: bool = True) -> AsyncIterator[MatchingFixture]:
    async with matching_fixture() as fixture:
        if persisted:
            async with fixture.data.database.session() as session, session.begin():
                await ThreeWayMatchRepository(
                    session, company_id=fixture.data.company_id
                ).add(fixture.aggregate, actor_id=fixture.data.actor_id)
        try:
            yield fixture
        finally:
            async with fixture.data.database.session() as session, session.begin():
                await session.execute(
                    delete(MatchingReevaluationModel).where(
                        MatchingReevaluationModel.company_id == fixture.data.company_id
                    )
                )
                await session.execute(
                    delete(MatchingSourceCursorModel).where(
                        MatchingSourceCursorModel.company_id == fixture.data.company_id
                    )
                )
                await session.execute(
                    delete(InboxEventModel).where(
                        InboxEventModel.consumer_name == MATCHING_EVENT_CONSUMER
                    )
                )
                await session.execute(
                    delete(OutboxEventModel).where(
                        OutboxEventModel.event_type == MATCHING_REEVALUATION_REQUESTED
                    )
                )
                await session.execute(
                    delete(AuditEventModel).where(
                        AuditEventModel.company_id == fixture.data.company_id,
                        AuditEventModel.operation == MATCHING_REEVALUATION_REQUESTED,
                    )
                )


def _event(
    fixture: MatchingFixture,
    *,
    message_type: str,
    producer_module: str,
    aggregate_type: str,
    aggregate_id: UUID,
    aggregate_version: int,
    occurred_at: datetime | None = None,
    payload: dict[str, object] | None = None,
) -> MessageEnvelope:
    return MessageEnvelope(
        message_id=uuid4(),
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=message_type,
        event_version=1,
        producer_module=producer_module,
        producer_domain=producer_module,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        company_id=fixture.data.company_id,
        branch_id=None,
        occurred_at=occurred_at or datetime.now(UTC),
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        payload={
            "company_id": str(fixture.data.company_id),
            "actor_id": str(fixture.data.actor_id),
            **(payload or {}),
        },
    )


def test_consumer_deduplicates_replays_and_ignores_older_versions() -> None:
    async def scenario() -> None:
        async with matching_event_fixture() as fixture:
            purchase = fixture.aggregate.purchase_order_snapshot.purchase_order
            latest = _event(
                fixture,
                message_type="PurchaseOrderApproved",
                producer_module="procurement",
                aggregate_type="purchase_order",
                aggregate_id=purchase.id,
                aggregate_version=purchase.version + 2,
            )
            consumer = MatchingEventConsumer(fixture.data.database)
            first = await consumer.consume(latest)
            replay = await consumer.consume(latest)
            assert first.processed is True
            assert first.duplicate is False
            assert replay.processed is False
            assert replay.duplicate is True

            stale = _event(
                fixture,
                message_type="PurchaseOrderApproved",
                producer_module="procurement",
                aggregate_type="purchase_order",
                aggregate_id=purchase.id,
                aggregate_version=purchase.version + 1,
                occurred_at=latest.occurred_at + timedelta(minutes=1),
            )
            assert (await consumer.consume(stale)).processed is True

            async with fixture.data.database.session() as session:
                cursor = await session.scalar(
                    select(MatchingSourceCursorModel).where(
                        MatchingSourceCursorModel.company_id == fixture.data.company_id,
                        MatchingSourceCursorModel.aggregate_id == purchase.id,
                    )
                )
                reevaluation = await session.scalar(
                    select(MatchingReevaluationModel).where(
                        MatchingReevaluationModel.company_id == fixture.data.company_id,
                        MatchingReevaluationModel.matching_session_id == fixture.aggregate.id,
                    )
                )
                receipts = tuple(
                    await session.scalars(
                        select(InboxEventModel).where(
                            InboxEventModel.consumer_name == MATCHING_EVENT_CONSUMER
                        )
                    )
                )
                outbox_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(
                        OutboxEventModel.event_type == MATCHING_REEVALUATION_REQUESTED,
                        OutboxEventModel.aggregate_id == fixture.aggregate.id,
                    )
                )
                assert cursor is not None
                assert cursor.aggregate_version == purchase.version + 2
                assert cursor.event_id == latest.message_id
                assert reevaluation is not None
                assert reevaluation.revision == 1
                assert len(reevaluation.reasons) == 1
                assert len(receipts) == 2
                assert {value.status for value in receipts} == {InboxStatus.PROCESSED}
                latest_receipt = next(
                    value for value in receipts if value.event_id == latest.message_id
                )
                assert latest_receipt.attempts == 2
                assert outbox_count == 1

    asyncio.run(scenario())


def test_consumer_merges_m11_and_m12_watermarks_without_snapshot_drift() -> None:
    async def scenario() -> None:
        async with matching_event_fixture() as fixture:
            aggregate = fixture.aggregate
            inbound = aggregate.receiving_fiscal_snapshot.fiscal_documents[0]
            provisional = aggregate.financial_snapshot.provisional_entry
            consumer = MatchingEventConsumer(fixture.data.database)
            await consumer.consume(
                _event(
                    fixture,
                    message_type="InboundFiscalDocumentManifested",
                    producer_module="fiscal",
                    aggregate_type="inbound_fiscal_document",
                    aggregate_id=inbound.id,
                    aggregate_version=inbound.version + 1,
                )
            )
            await consumer.consume(
                _event(
                    fixture,
                    message_type="FiscalReceivingReconciled",
                    producer_module="fiscal",
                    aggregate_type="fiscal_receiving_reconciliation",
                    aggregate_id=uuid4(),
                    aggregate_version=1,
                    payload={
                        "purchase_order_id": str(
                            aggregate.purchase_order_snapshot.purchase_order.id
                        ),
                        "goods_receipt_id": str(
                            aggregate.receiving_fiscal_snapshot.goods_receipts[0].id
                        ),
                        "inbound_fiscal_document_id": str(inbound.id),
                    },
                )
            )
            await consumer.consume(
                _event(
                    fixture,
                    message_type="ProvisionalFinancialEntryConverted",
                    producer_module="finance",
                    aggregate_type="provisional_financial_entry",
                    aggregate_id=provisional.id,
                    aggregate_version=provisional.version + 1,
                )
            )

            async with fixture.data.database.session() as session:
                reevaluation = await session.scalar(
                    select(MatchingReevaluationModel).where(
                        MatchingReevaluationModel.company_id == fixture.data.company_id,
                        MatchingReevaluationModel.matching_session_id == aggregate.id,
                    )
                )
                persisted = await ThreeWayMatchRepository(
                    session, company_id=fixture.data.company_id
                ).get(aggregate.id)
                assert reevaluation is not None
                assert reevaluation.status == "PENDING"
                assert reevaluation.revision == 3
                assert set(reevaluation.source_watermarks) == {
                    f"fiscal:inbound_fiscal_document:{inbound.id}",
                    next(
                        key
                        for key in reevaluation.source_watermarks
                        if key.startswith("fiscal:fiscal_receiving_reconciliation:")
                    ),
                    f"finance:provisional_financial_entry:{provisional.id}",
                }
                assert persisted == aggregate

    asyncio.run(scenario())


def test_concurrent_out_of_order_delivery_preserves_highest_source_version() -> None:
    async def scenario() -> None:
        async with matching_event_fixture() as fixture:
            purchase = fixture.aggregate.purchase_order_snapshot.purchase_order
            low = _event(
                fixture,
                message_type="PurchaseOrderApproved",
                producer_module="procurement",
                aggregate_type="purchase_order",
                aggregate_id=purchase.id,
                aggregate_version=purchase.version + 4,
                occurred_at=datetime.now(UTC) + timedelta(minutes=2),
            )
            high = _event(
                fixture,
                message_type="PurchaseOrderCancelled",
                producer_module="procurement",
                aggregate_type="purchase_order",
                aggregate_id=purchase.id,
                aggregate_version=purchase.version + 5,
                occurred_at=datetime.now(UTC),
            )
            consumer = MatchingEventConsumer(fixture.data.database)
            results = await asyncio.gather(consumer.consume(low), consumer.consume(high))
            assert all(value.processed for value in results)

            async with fixture.data.database.session() as session:
                cursor = await session.scalar(
                    select(MatchingSourceCursorModel).where(
                        MatchingSourceCursorModel.company_id == fixture.data.company_id,
                        MatchingSourceCursorModel.aggregate_id == purchase.id,
                    )
                )
                reevaluation = await session.scalar(
                    select(MatchingReevaluationModel).where(
                        MatchingReevaluationModel.company_id == fixture.data.company_id,
                        MatchingReevaluationModel.matching_session_id == fixture.aggregate.id,
                    )
                )
                processed = await session.scalar(
                    select(func.count())
                    .select_from(InboxEventModel)
                    .where(
                        InboxEventModel.consumer_name == MATCHING_EVENT_CONSUMER,
                        InboxEventModel.status == InboxStatus.PROCESSED,
                    )
                )
                assert cursor is not None
                assert cursor.aggregate_version == high.aggregate_version
                assert cursor.event_id == high.message_id
                assert cursor.invalidates_snapshot is True
                assert reevaluation is not None
                assert 1 <= reevaluation.revision <= 2
                assert processed == 2

    asyncio.run(scenario())


def test_event_received_before_session_creation_is_applied_after_persistence() -> None:
    async def scenario() -> None:
        async with matching_event_fixture(persisted=False) as fixture:
            aggregate = fixture.aggregate
            receipt = aggregate.receiving_fiscal_snapshot.goods_receipts[0]
            event = _event(
                fixture,
                message_type="GoodsReceiptPosted",
                producer_module="procurement",
                aggregate_type="goods_receipt",
                aggregate_id=receipt.id,
                aggregate_version=receipt.version + 2,
            )
            assert (await MatchingEventConsumer(fixture.data.database).consume(event)).processed
            async with fixture.data.database.session() as session, session.begin():
                await ThreeWayMatchRepository(
                    session, company_id=fixture.data.company_id
                ).add(aggregate, actor_id=fixture.data.actor_id)
                event_ids = await flag_matching_from_source_cursors(session, aggregate)
                assert len(event_ids) == 1

            async with fixture.data.database.session() as session:
                reevaluation = await session.scalar(
                    select(MatchingReevaluationModel).where(
                        MatchingReevaluationModel.company_id == fixture.data.company_id,
                        MatchingReevaluationModel.matching_session_id == aggregate.id,
                    )
                )
                persisted = await ThreeWayMatchRepository(
                    session, company_id=fixture.data.company_id
                ).get(aggregate.id)
                assert reevaluation is not None
                assert reevaluation.revision == 1
                assert persisted == aggregate

    asyncio.run(scenario())


def test_consumer_rejects_cross_tenant_payload_before_inbox_reservation() -> None:
    async def scenario() -> None:
        async with matching_event_fixture() as fixture:
            purchase = fixture.aggregate.purchase_order_snapshot.purchase_order
            envelope = _event(
                fixture,
                message_type="PurchaseOrderApproved",
                producer_module="procurement",
                aggregate_type="purchase_order",
                aggregate_id=purchase.id,
                aggregate_version=purchase.version + 1,
                payload={"company_id": str(fixture.data.other_company_id)},
            )
            with pytest.raises(ValueError, match="company boundary"):
                await MatchingEventConsumer(fixture.data.database).consume(envelope)
            async with fixture.data.database.session() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(InboxEventModel)
                        .where(InboxEventModel.event_id == envelope.message_id)
                    )
                    == 0
                )

    asyncio.run(scenario())


def test_migration_0042_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    tables = set(inspect(sync_connection).get_table_names(schema="procurement"))
                    event_tables = {"matching_source_cursor", "matching_reevaluation"}
                    assert event_tables.issubset(tables) is expected

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0041")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0042")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")
