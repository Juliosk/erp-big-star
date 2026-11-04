"""Reactive Cash Flow composition through Inbox, cursors and durable work."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.engine import Connection

from erp.modules.finance.application import (
    CashFlowCompositionService,
    UnavailableReceivableProvider,
)
from erp.modules.finance.domain import BusinessCalendar, CashFlowEngine
from erp.modules.finance.infrastructure import (
    CASH_FLOW_EVENT_CONSUMER,
    CASH_FLOW_PROJECTION_RECOMPOSED,
    BankStatementRepository,
    CashFlowAlertModel,
    CashFlowEventConsumer,
    CashFlowProjectionRepository,
    CashFlowProjectionSnapshotModel,
    CashFlowRecompositionRequestModel,
    CashFlowRecompositionWorker,
    CashFlowSourceCursorModel,
    PostgresBankPositionProvider,
    PostgresPayableCommitmentProvider,
    accept_cash_flow_source_cursor,
    enqueue_cash_flow_recompositions,
)
from erp.platform.audit.models import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.inbox import InboxEventModel, InboxStatus
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.test_cash_flow_composition_service import (
    _bank_statement,
    _command,
    composition_fixture,
)
from tests.integration.test_treasury_repository import TreasuryFixture

pytestmark = pytest.mark.integration

_RECOMPOSED_AT = datetime(2026, 12, 1, 9, tzinfo=UTC)


@asynccontextmanager
async def cash_flow_event_fixture() -> AsyncIterator[TreasuryFixture]:
    async with composition_fixture() as fixture:
        data = fixture.matching.data
        try:
            yield fixture
        finally:
            async with data.database.session() as session, session.begin():
                alert_ids = tuple(
                    await session.scalars(
                        select(CashFlowAlertModel.id).where(
                            CashFlowAlertModel.company_id.in_(
                                (data.company_id, data.other_company_id)
                            )
                        )
                    )
                )
                if alert_ids:
                    await session.execute(
                        delete(AuditEventModel).where(
                            AuditEventModel.entity_type == "cash_flow_alert",
                            AuditEventModel.entity_id.in_(alert_ids),
                        )
                    )
                    await session.execute(
                        delete(OutboxEventModel).where(
                            OutboxEventModel.aggregate_type == "cash_flow_alert",
                            OutboxEventModel.aggregate_id.in_(alert_ids),
                        )
                    )
                await session.execute(
                    text("SET LOCAL erp.allow_cash_flow_alert_cleanup = 'on'")
                )
                await session.execute(
                    delete(CashFlowAlertModel).where(
                        CashFlowAlertModel.company_id.in_(
                            (data.company_id, data.other_company_id)
                        )
                    )
                )
                await session.execute(
                    delete(CashFlowRecompositionRequestModel).where(
                        CashFlowRecompositionRequestModel.company_id.in_(
                            (data.company_id, data.other_company_id)
                        )
                    )
                )
                await session.execute(
                    delete(CashFlowSourceCursorModel).where(
                        CashFlowSourceCursorModel.company_id.in_(
                            (data.company_id, data.other_company_id)
                        )
                    )
                )
                await session.execute(
                    delete(InboxEventModel).where(
                        InboxEventModel.consumer_name == CASH_FLOW_EVENT_CONSUMER
                    )
                )
                await session.execute(
                    delete(OutboxEventModel).where(
                        OutboxEventModel.event_type == CASH_FLOW_PROJECTION_RECOMPOSED
                    )
                )


def _worker() -> CashFlowRecompositionWorker:
    return CashFlowRecompositionWorker(clock=lambda: _RECOMPOSED_AT)


async def _seed_projection(
    fixture: TreasuryFixture,
    projection_id: UUID,
    *,
    scenario_id: UUID | None = None,
) -> None:
    data = fixture.matching.data
    async with data.database.session() as session, session.begin():
        await CashFlowCompositionService(
            engine=CashFlowEngine(BusinessCalendar()),
            bank_positions=PostgresBankPositionProvider(session),
            payables=PostgresPayableCommitmentProvider(session),
            receivables=UnavailableReceivableProvider(),
            projections=CashFlowProjectionRepository(session, company_id=data.company_id),
        ).compose(
            _command(
                company_id=data.company_id,
                projection_id=projection_id,
                scenario_id=scenario_id,
            ),
            actor_id=data.actor_id,
        )


def _event(
    fixture: TreasuryFixture,
    *,
    aggregate_id: UUID | None = None,
    aggregate_version: int = 1,
    occurred_at: datetime | None = None,
    payload: dict[str, object] | None = None,
) -> MessageEnvelope:
    data = fixture.matching.data
    return MessageEnvelope(
        message_id=uuid4(),
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type="BankMovementReconciled",
        event_version=1,
        producer_module="finance",
        producer_domain="bank_reconciliation",
        aggregate_type="bank_movement",
        aggregate_id=aggregate_id or uuid4(),
        aggregate_version=aggregate_version,
        company_id=data.company_id,
        branch_id=None,
        occurred_at=occurred_at or datetime(2026, 12, 1, 8, 30, tzinfo=UTC),
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        payload={"company_id": str(data.company_id), **(payload or {})},
    )


def test_financial_event_recomposes_snapshot_once_and_publishes_outbox() -> None:
    async def scenario() -> None:
        async with cash_flow_event_fixture() as fixture:
            data = fixture.matching.data
            projection_id = uuid4()
            await _seed_projection(fixture, projection_id)
            statement = _bank_statement(company_id=data.company_id)
            async with data.database.session() as session, session.begin():
                await BankStatementRepository(session, company_id=data.company_id).add(
                    statement,
                    actor_id=data.actor_id,
                    original_file_name="cash-flow-event.ofx",
                    file_size_bytes=491,
                )
            event = _event(fixture, aggregate_id=statement.movements[0].id)
            consumer = CashFlowEventConsumer(data.database, worker=_worker())
            first = await consumer.consume(event)
            replay = await consumer.consume(event)
            assert first.processed is True
            assert replay.duplicate is True

            async with data.database.session() as session:
                repository = CashFlowProjectionRepository(session, company_id=data.company_id)
                versions = await repository.versions(projection_id)
                assert [value.version for value in versions] == [1, 2]
                assert versions[0].opening_balance.amount == 0
                assert versions[1].opening_balance.amount == statement.closing_balance
                assert await session.scalar(
                    select(func.count())
                    .select_from(CashFlowRecompositionRequestModel)
                    .where(CashFlowRecompositionRequestModel.company_id == data.company_id)
                ) == 0
                outgoing = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_type == CASH_FLOW_PROJECTION_RECOMPOSED,
                        OutboxEventModel.causation_id == event.message_id,
                    )
                )
                assert outgoing is not None
                assert outgoing.payload["aggregate_version"] == 2
                assert outgoing.payload["payload"]["source_event"] == event.message_type

    asyncio.run(scenario())


def test_monotonic_cursor_ignores_stale_delivery_but_inbox_records_both() -> None:
    async def scenario() -> None:
        async with cash_flow_event_fixture() as fixture:
            data = fixture.matching.data
            projection_id = uuid4()
            aggregate_id = uuid4()
            await _seed_projection(fixture, projection_id)
            latest = _event(
                fixture,
                aggregate_id=aggregate_id,
                aggregate_version=3,
                occurred_at=datetime(2026, 12, 1, 8, tzinfo=UTC),
            )
            stale = _event(
                fixture,
                aggregate_id=aggregate_id,
                aggregate_version=2,
                occurred_at=datetime(2026, 12, 1, 9, tzinfo=UTC),
            )
            consumer = CashFlowEventConsumer(data.database, worker=_worker())
            assert (await consumer.consume(latest)).processed
            assert (await consumer.consume(stale)).processed

            async with data.database.session() as session:
                cursor = await session.get(
                    CashFlowSourceCursorModel,
                    (data.company_id, "finance", "bank_movement", aggregate_id),
                )
                versions = await CashFlowProjectionRepository(
                    session, company_id=data.company_id
                ).versions(projection_id)
                processed = await session.scalar(
                    select(func.count())
                    .select_from(InboxEventModel)
                    .where(
                        InboxEventModel.consumer_name == CASH_FLOW_EVENT_CONSUMER,
                        InboxEventModel.status == InboxStatus.PROCESSED,
                    )
                )
                assert cursor is not None
                assert cursor.aggregate_version == 3
                assert [value.version for value in versions] == [1, 2]
                assert processed == 2

    asyncio.run(scenario())


def test_skip_locked_leaves_durable_work_for_a_later_worker() -> None:
    async def scenario() -> None:
        async with cash_flow_event_fixture() as fixture:
            data = fixture.matching.data
            projection_id = uuid4()
            scenario_id = uuid4()
            await _seed_projection(fixture, projection_id, scenario_id=scenario_id)
            await _seed_projection(fixture, projection_id, scenario_id=scenario_id)
            event = _event(fixture)
            async with data.database.session() as session, session.begin():
                assert await accept_cash_flow_source_cursor(session, event)
                await enqueue_cash_flow_recompositions(
                    session,
                    event,
                    requested_at=datetime(2026, 12, 1, 8, 45, tzinfo=UTC),
                )

            async with data.database.session() as locking_session:
                transaction = await locking_session.begin()
                await locking_session.scalar(
                    select(CashFlowProjectionSnapshotModel)
                    .where(
                        CashFlowProjectionSnapshotModel.company_id == data.company_id,
                        CashFlowProjectionSnapshotModel.id == projection_id,
                        CashFlowProjectionSnapshotModel.version == 2,
                    )
                    .with_for_update()
                )
                async with data.database.session() as worker_session, worker_session.begin():
                    assert await _worker().run_pending(
                        worker_session,
                        company_id=data.company_id,
                    ) == ()
                await transaction.commit()

            async with data.database.session() as session, session.begin():
                assert await _worker().run_pending(session, company_id=data.company_id) == (
                    projection_id,
                )
            async with data.database.session() as session:
                versions = await CashFlowProjectionRepository(
                    session, company_id=data.company_id
                ).versions(projection_id)
                assert [value.version for value in versions] == [1, 2, 3]

    asyncio.run(scenario())


def test_outbox_failure_rolls_back_snapshot_and_keeps_retryable_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_enqueue(self: OutboxService, *_: object, **__: object) -> UUID:
        del self
        raise RuntimeError("outbox unavailable")

    original = OutboxService.enqueue
    monkeypatch.setattr(OutboxService, "enqueue", fail_enqueue)

    async def scenario() -> None:
        async with cash_flow_event_fixture() as fixture:
            data = fixture.matching.data
            projection_id = uuid4()
            await _seed_projection(fixture, projection_id)
            event = _event(fixture)
            consumer = CashFlowEventConsumer(data.database, worker=_worker())
            with pytest.raises(RuntimeError, match="outbox unavailable"):
                await consumer.consume(event)

            async with data.database.session() as session:
                versions = await CashFlowProjectionRepository(
                    session, company_id=data.company_id
                ).versions(projection_id)
                pending = await session.get(
                    CashFlowRecompositionRequestModel,
                    (data.company_id, projection_id),
                )
                assert [value.version for value in versions] == [1]
                assert pending is not None

            monkeypatch.setattr(OutboxService, "enqueue", original)
            replay = await consumer.consume(event)
            assert replay.duplicate is True
            async with data.database.session() as session:
                versions = await CashFlowProjectionRepository(
                    session, company_id=data.company_id
                ).versions(projection_id)
                assert [value.version for value in versions] == [1, 2]
                assert await session.get(
                    CashFlowRecompositionRequestModel,
                    (data.company_id, projection_id),
                ) is None

    asyncio.run(scenario())


def test_consumer_rejects_cross_tenant_payload_before_inbox() -> None:
    async def scenario() -> None:
        async with cash_flow_event_fixture() as fixture:
            data = fixture.matching.data
            event = _event(
                fixture,
                payload={"company_id": str(data.other_company_id)},
            )
            with pytest.raises(ValueError, match="company boundary"):
                await CashFlowEventConsumer(data.database, worker=_worker()).consume(event)
            async with data.database.session() as session:
                assert await session.scalar(
                    select(func.count())
                    .select_from(InboxEventModel)
                    .where(InboxEventModel.consumer_name == CASH_FLOW_EVENT_CONSUMER)
                ) == 0

    asyncio.run(scenario())


def test_consumer_rejects_unsupported_envelope_and_invalid_worker_limit() -> None:
    async def scenario() -> None:
        async with cash_flow_event_fixture() as fixture:
            data = fixture.matching.data
            unsupported = _event(fixture).model_copy(update={"message_type": "UnknownFact"})
            with pytest.raises(ValueError, match="Unsupported Cash Flow"):
                await CashFlowEventConsumer(data.database, worker=_worker()).consume(unsupported)
            async with data.database.session() as session:
                with pytest.raises(ValueError, match="between 1 and 500"):
                    await _worker().run_pending(
                        session,
                        company_id=data.company_id,
                        limit=0,
                    )

    asyncio.run(scenario())


def test_migration_0049_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        from erp.platform.database import Database

        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    tables = set(inspect(sync_connection).get_table_names(schema="finance"))
                    event_tables = {
                        "cash_flow_source_cursor",
                        "cash_flow_recomposition_request",
                    }
                    assert event_tables.issubset(tables) is expected

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0048")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0049")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")


__all__: list[str] = []
