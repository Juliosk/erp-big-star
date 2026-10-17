"""M12 Treasury Inbox resilience, monotonic cursors and reassessment effects."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.infrastructure import (
    PAYMENT_BATCH_BLOCKED,
    PAYMENT_BATCH_REEVALUATION_CLEARED,
    TREASURY_EVENT_CONSUMER,
    PaymentBatchRepository,
    PaymentBatchReviewModel,
    TreasuryEventConsumer,
    TreasurySourceCursorModel,
    apply_treasury_source_cursors,
    require_payment_batch_unblocked,
)
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.errors import ApplicationError
from erp.platform.inbox import InboxEventModel, InboxStatus
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.test_treasury_repository import TreasuryFixture, treasury_fixture

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class TreasuryEventFixture:
    treasury: TreasuryFixture
    persisted: bool


@asynccontextmanager
async def treasury_event_fixture(
    *,
    persisted: bool = True,
) -> AsyncIterator[TreasuryEventFixture]:
    async with treasury_fixture() as treasury:
        data = treasury.matching.data
        if persisted:
            async with data.database.session() as session, session.begin():
                await PaymentBatchRepository(session, company_id=data.company_id).add(
                    treasury.batch,
                    actor_id=treasury.batch_creator,
                )
        try:
            yield TreasuryEventFixture(treasury, persisted)
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(InboxEventModel).where(
                        InboxEventModel.consumer_name == TREASURY_EVENT_CONSUMER
                    )
                )
                await session.execute(
                    delete(OutboxEventModel).where(
                        OutboxEventModel.source_module == "finance",
                        OutboxEventModel.aggregate_id == treasury.batch.id,
                    )
                )
                await session.execute(
                    delete(AuditEventModel).where(
                        AuditEventModel.company_id == data.company_id,
                        AuditEventModel.module == "finance",
                        AuditEventModel.entity_type == "payment_batch",
                        AuditEventModel.entity_id == treasury.batch.id,
                    )
                )
                await session.execute(
                    delete(PaymentBatchReviewModel).where(
                        PaymentBatchReviewModel.company_id == data.company_id
                    )
                )
                await session.execute(
                    delete(TreasurySourceCursorModel).where(
                        TreasurySourceCursorModel.company_id == data.company_id
                    )
                )


def test_concurrent_out_of_order_events_keep_highest_version_and_deduplicate() -> None:
    async def scenario() -> None:
        async with treasury_event_fixture() as fixture:
            treasury = fixture.treasury
            data = treasury.matching.data
            payable_id = treasury.batch.items[0].payable_id
            now = datetime.now(UTC)
            low = _event(
                fixture,
                message_type="PayableAdjusted",
                producer="finance",
                aggregate_type="payable",
                aggregate_id=payable_id,
                aggregate_version=4,
                occurred_at=now + timedelta(minutes=2),
                payload={"amount": "125.40"},
            )
            high = _event(
                fixture,
                message_type="PayableRejected",
                producer="finance",
                aggregate_type="payable",
                aggregate_id=payable_id,
                aggregate_version=5,
                occurred_at=now,
            )
            consumer = TreasuryEventConsumer(data.database)
            results = await asyncio.gather(consumer.consume(low), consumer.consume(high))
            assert all(value.processed for value in results)
            replay = await consumer.consume(high)
            assert replay.duplicate is True
            assert replay.processed is False

            async with data.database.session() as session:
                cursor = await session.scalar(
                    select(TreasurySourceCursorModel).where(
                        TreasurySourceCursorModel.company_id == data.company_id,
                        TreasurySourceCursorModel.aggregate_id == payable_id,
                    )
                )
                review = await _review(session, data.company_id, treasury.batch.id)
                inbox_count = await session.scalar(
                    select(func.count())
                    .select_from(InboxEventModel)
                    .where(
                        InboxEventModel.consumer_name == TREASURY_EVENT_CONSUMER,
                        InboxEventModel.status == InboxStatus.PROCESSED,
                    )
                )
                assert cursor is not None
                assert cursor.aggregate_version == 5
                assert cursor.event_id == high.message_id
                assert review is not None
                assert review.status == "BLOCKED"
                assert review.blocked is True
                assert 1 <= review.revision <= 2
                assert inbox_count == 2

    asyncio.run(scenario())


def test_matching_discrepancy_blocks_and_newer_override_clears_remittance() -> None:
    async def scenario() -> None:
        async with treasury_event_fixture() as fixture:
            treasury = fixture.treasury
            data = treasury.matching.data
            matching_id = treasury.batch.items[0].matching_session_id
            consumer = TreasuryEventConsumer(data.database)
            blocked = _event(
                fixture,
                message_type="MatchingDiscrepancyDetected",
                producer="procurement",
                aggregate_type="three_way_match_session",
                aggregate_id=matching_id,
                aggregate_version=4,
            )
            cleared = _event(
                fixture,
                message_type="MatchingOverrideApproved",
                producer="procurement",
                aggregate_type="three_way_match_session",
                aggregate_id=matching_id,
                aggregate_version=5,
                occurred_at=blocked.occurred_at + timedelta(seconds=1),
            )
            assert (await consumer.consume(blocked)).processed
            async with data.database.session() as session:
                with pytest.raises(ApplicationError) as captured:
                    await require_payment_batch_unblocked(
                        session,
                        company_id=data.company_id,
                        payment_batch_id=treasury.batch.id,
                    )
                assert captured.value.code == "PAYMENT_BATCH_REVIEW_BLOCKED"

            assert (await consumer.consume(cleared)).processed
            async with data.database.session() as session:
                await require_payment_batch_unblocked(
                    session,
                    company_id=data.company_id,
                    payment_batch_id=treasury.batch.id,
                )
                review = await _review(session, data.company_id, treasury.batch.id)
                event_types = set(
                    await session.scalars(
                        select(OutboxEventModel.event_type).where(
                            OutboxEventModel.aggregate_id == treasury.batch.id,
                            OutboxEventModel.event_type.in_(
                                (
                                    PAYMENT_BATCH_BLOCKED,
                                    PAYMENT_BATCH_REEVALUATION_CLEARED,
                                )
                            ),
                        )
                    )
                )
                assert review is not None
                assert review.status == "CLEARED"
                assert review.blocked is False
                assert review.revision == 2
                assert event_types == {
                    PAYMENT_BATCH_BLOCKED,
                    PAYMENT_BATCH_REEVALUATION_CLEARED,
                }

    asyncio.run(scenario())


def test_m22_decision_reassesses_only_targeted_pending_batch() -> None:
    async def scenario() -> None:
        async with treasury_event_fixture() as fixture:
            treasury = fixture.treasury
            data = treasury.matching.data
            pending = treasury.batch.submit_for_approval()
            async with data.database.session() as session, session.begin():
                await PaymentBatchRepository(session, company_id=data.company_id).save(
                    pending,
                    actor_id=treasury.batch_creator,
                    expected_version=treasury.batch.version,
                )
            workflow_id = uuid4()
            rejected = _event(
                fixture,
                message_type="ApprovalDecisionMade",
                producer="workflow",
                aggregate_type="workflow_instance",
                aggregate_id=workflow_id,
                aggregate_version=1,
                payload={
                    "source_module": "finance",
                    "source_type": "PAYMENT_BATCH",
                    "source_id": str(treasury.batch.id),
                    "decision": "REJECTED",
                    "decided_by": str(treasury.batch_approver),
                },
            )
            approved = _event(
                fixture,
                message_type="ApprovalDecisionMade",
                producer="workflow",
                aggregate_type="workflow_instance",
                aggregate_id=workflow_id,
                aggregate_version=2,
                occurred_at=rejected.occurred_at + timedelta(seconds=1),
                payload={
                    "source_module": "finance",
                    "source_type": "PAYMENT_BATCH",
                    "source_id": str(treasury.batch.id),
                    "decision": "APPROVED",
                    "decided_by": str(treasury.batch_approver),
                },
            )
            consumer = TreasuryEventConsumer(data.database)
            await consumer.consume(rejected)
            await consumer.consume(approved)
            async with data.database.session() as session:
                review = await _review(session, data.company_id, treasury.batch.id)
                persisted = await PaymentBatchRepository(session, company_id=data.company_id).get(
                    treasury.batch.id
                )
                assert review is not None
                assert review.status == "CLEARED"
                assert review.revision == 2
                assert persisted == pending

    asyncio.run(scenario())


def test_source_event_delivered_before_batch_is_applied_after_persistence() -> None:
    async def scenario() -> None:
        async with treasury_event_fixture(persisted=False) as fixture:
            treasury = fixture.treasury
            data = treasury.matching.data
            matching_id = treasury.batch.items[0].matching_session_id
            event = _event(
                fixture,
                message_type="MatchingDiscrepancyDetected",
                producer="procurement",
                aggregate_type="three_way_match_session",
                aggregate_id=matching_id,
                aggregate_version=9,
            )
            assert (await TreasuryEventConsumer(data.database).consume(event)).processed
            async with data.database.session() as session, session.begin():
                await PaymentBatchRepository(session, company_id=data.company_id).add(
                    treasury.batch,
                    actor_id=treasury.batch_creator,
                )
                event_ids = await apply_treasury_source_cursors(session, treasury.batch)
                assert len(event_ids) == 1
            async with data.database.session() as session:
                review = await _review(session, data.company_id, treasury.batch.id)
                assert review is not None
                assert review.status == "BLOCKED"
                assert review.revision == 1

    asyncio.run(scenario())


def test_outbox_failure_rolls_back_inbox_cursor_review_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_enqueue(self: OutboxService, *_: object, **__: object) -> UUID:
        del self
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(OutboxService, "enqueue", fail_enqueue)

    async def scenario() -> None:
        async with treasury_event_fixture() as fixture:
            treasury = fixture.treasury
            data = treasury.matching.data
            event = _event(
                fixture,
                message_type="PayableAdjusted",
                producer="finance",
                aggregate_type="payable",
                aggregate_id=treasury.batch.items[0].payable_id,
                aggregate_version=8,
            )
            with pytest.raises(RuntimeError, match="outbox unavailable"):
                await TreasuryEventConsumer(data.database).consume(event)
            async with data.database.session() as session:
                counts = [
                    await session.scalar(select(func.count()).select_from(model))
                    for model in (
                        TreasurySourceCursorModel,
                        PaymentBatchReviewModel,
                    )
                ]
                inbox = await session.scalar(
                    select(func.count())
                    .select_from(InboxEventModel)
                    .where(InboxEventModel.event_id == event.message_id)
                )
                audit = await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(
                        AuditEventModel.company_id == data.company_id,
                        AuditEventModel.entity_id == treasury.batch.id,
                    )
                )
                assert counts == [0, 0]
                assert inbox == 0
                assert audit == 0

    asyncio.run(scenario())


def test_consumer_rejects_cross_tenant_and_unsupported_payloads_before_inbox() -> None:
    async def scenario() -> None:
        async with treasury_event_fixture() as fixture:
            treasury = fixture.treasury
            data = treasury.matching.data
            crossing = _event(
                fixture,
                message_type="PayableAdjusted",
                producer="finance",
                aggregate_type="payable",
                aggregate_id=treasury.batch.items[0].payable_id,
                aggregate_version=2,
                payload={"company_id": str(data.other_company_id)},
            )
            consumer = TreasuryEventConsumer(data.database)
            with pytest.raises(ValueError, match="company boundary"):
                await consumer.consume(crossing)
            invalid_workflow = _event(
                fixture,
                message_type="ApprovalDecisionMade",
                producer="workflow",
                aggregate_type="workflow_instance",
                aggregate_id=uuid4(),
                aggregate_version=1,
                payload={
                    "source_module": "procurement",
                    "source_type": "PURCHASE_ORDER",
                    "source_id": str(uuid4()),
                    "decision": "APPROVED",
                },
            )
            with pytest.raises(ValueError, match="does not target"):
                await consumer.consume(invalid_workflow)
            async with data.database.session() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(InboxEventModel)
                        .where(
                            InboxEventModel.event_id.in_(
                                (crossing.message_id, invalid_workflow.message_id)
                            )
                        )
                    )
                    == 0
                )

    asyncio.run(scenario())


def test_migration_0045_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        from erp.platform.database import Database

        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    tables = set(inspect(sync_connection).get_table_names(schema="finance"))
                    event_tables = {
                        "treasury_source_cursor",
                        "payment_batch_review",
                    }
                    assert event_tables.issubset(tables) is expected

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0044")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0045")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")


async def _review(
    session: AsyncSession,
    company_id: UUID,
    payment_batch_id: UUID,
) -> PaymentBatchReviewModel | None:
    return cast(
        PaymentBatchReviewModel | None,
        await session.scalar(
            select(PaymentBatchReviewModel).where(
                PaymentBatchReviewModel.company_id == company_id,
                PaymentBatchReviewModel.payment_batch_id == payment_batch_id,
            )
        ),
    )


def _event(
    fixture: TreasuryEventFixture,
    *,
    message_type: str,
    producer: str,
    aggregate_type: str,
    aggregate_id: UUID,
    aggregate_version: int,
    occurred_at: datetime | None = None,
    payload: dict[str, object] | None = None,
) -> MessageEnvelope:
    data = fixture.treasury.matching.data
    return MessageEnvelope(
        message_id=uuid4(),
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=message_type,
        event_version=1,
        producer_module=producer,
        producer_domain=producer,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        company_id=data.company_id,
        branch_id=None,
        occurred_at=occurred_at or datetime.now(UTC),
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        payload={"company_id": str(data.company_id), **(payload or {})},
    )


__all__: list[str] = []
