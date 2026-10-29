"""M12 bank-reconciliation Inbox resilience and reactive matching integration."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, func, inspect, select, update

from erp.modules.finance.application import (
    BankCandidateSource,
    BankConciliationClassification,
    BankConciliationService,
)
from erp.modules.finance.domain import (
    BankMovement,
    BankMovementDirection,
    BankMovementStatus,
    BankStatement,
    BankStatementSource,
    BankTransactionKind,
    ReconciliationDecision,
    ReconciliationReason,
    ReconciliationStatus,
)
from erp.modules.finance.infrastructure import (
    BANK_MOVEMENT_RECONCILED,
    BANK_RECONCILIATION_EVENT_CONSUMER,
    BANK_RECONCILIATION_REVIEW_REQUIRED,
    BankReconciliationCandidateModel,
    BankReconciliationEventConsumer,
    BankReconciliationSourceCursorModel,
    BankStatementRepository,
    EventBankCandidateProvider,
    PayableInstallmentModel,
    PayableModel,
)
from erp.platform.config import get_settings
from erp.platform.inbox import InboxEventModel, InboxStatus
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.test_bank_statement_repository import bank_statement_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


@asynccontextmanager
async def reconciliation_event_fixture() -> AsyncIterator[ProcurementFixture]:
    async with bank_statement_fixture() as data:
        try:
            yield data
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(InboxEventModel).where(
                        InboxEventModel.consumer_name == BANK_RECONCILIATION_EVENT_CONSUMER
                    )
                )
                await session.execute(
                    delete(OutboxEventModel).where(
                        OutboxEventModel.source_module == "finance",
                        OutboxEventModel.event_type.in_(
                            (
                                BANK_MOVEMENT_RECONCILED,
                                BANK_RECONCILIATION_REVIEW_REQUIRED,
                            )
                        ),
                    )
                )
                await session.execute(
                    delete(BankReconciliationCandidateModel).where(
                        BankReconciliationCandidateModel.company_id.in_(
                            (data.company_id, data.other_company_id)
                        )
                    )
                )
                await session.execute(
                    delete(BankReconciliationSourceCursorModel).where(
                        BankReconciliationSourceCursorModel.company_id.in_(
                            (data.company_id, data.other_company_id)
                        )
                    )
                )


def _statement(
    data: ProcurementFixture,
    *,
    direction: BankMovementDirection,
    amount: Decimal = Decimal("100.00"),
    document_number: str = "DOC-184",
) -> BankStatement:
    statement_id = uuid4()
    account_id = uuid4()
    return BankStatement(
        id=statement_id,
        company_id=data.company_id,
        bank_account_id=account_id,
        bank_code="001",
        account_reference="123456-7",
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        imported_at=datetime(2026, 10, 29, 9, tzinfo=UTC),
        source=BankStatementSource.OFX,
        source_hash=uuid4().hex * 2,
        movements=(
            BankMovement(
                id=uuid4(),
                company_id=data.company_id,
                bank_account_id=account_id,
                external_id=f"MOV-{uuid4()}",
                booked_on=date(2026, 10, 28),
                amount=amount,
                direction=direction,
                kind=(
                    BankTransactionKind.PAYMENT
                    if direction is BankMovementDirection.DEBIT
                    else BankTransactionKind.RECEIPT
                ),
                description="Reactive matching event fixture",
                document_number=document_number,
            ),
        ),
    )


async def _persist_statement(data: ProcurementFixture, statement: BankStatement) -> None:
    async with data.database.session() as session, session.begin():
        await BankStatementRepository(session, company_id=data.company_id).add(
            statement,
            actor_id=data.actor_id,
            original_file_name="event-184.ofx",
            file_size_bytes=184,
        )


async def _seed_scheduled_payable(
    data: ProcurementFixture,
    *,
    amount: Decimal = Decimal("100.00"),
    document_number: str = "DOC-184",
) -> tuple[UUID, UUID]:
    payable_id = uuid4()
    installment_id = uuid4()
    async with data.database.session() as session, session.begin():
        session.add(
            PayableModel(
                id=payable_id,
                company_id=data.company_id,
                document_number=document_number,
                supplier_id=uuid4(),
                supplier_tax_id="12345678000195",
                provisional_entry_id=None,
                currency="BRL",
                nominal_amount=amount,
                interest_amount=Decimal("0.00"),
                discount_amount=Decimal("0.00"),
                surcharge_amount=Decimal("0.00"),
                status="SCHEDULED",
                decision_by=uuid4(),
                decision_reason="Approved for event fixture",
                version=1,
                created_by=data.actor_id,
                updated_by=data.actor_id,
            )
        )
        await session.flush()
        session.add(
            PayableInstallmentModel(
                id=installment_id,
                company_id=data.company_id,
                payable_id=payable_id,
                installment_number=1,
                due_date=date(2026, 10, 27),
                amount=amount,
                status="SCHEDULED",
                schedule_id=uuid4(),
                paid_on=None,
                payment_reference=None,
                created_by=data.actor_id,
                updated_by=data.actor_id,
            )
        )
    return payable_id, installment_id


def _event(
    data: ProcurementFixture,
    *,
    message_type: str,
    producer_domain: str,
    aggregate_type: str,
    aggregate_id: UUID,
    aggregate_version: int = 1,
    occurred_at: datetime | None = None,
    payload: dict[str, object] | None = None,
) -> MessageEnvelope:
    return MessageEnvelope(
        message_id=uuid4(),
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=message_type,
        event_version=1,
        producer_module="finance",
        producer_domain=producer_domain,
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


def test_confirmed_payable_event_reconciles_pending_debit_once_and_emits_outbox() -> None:
    async def scenario() -> None:
        async with reconciliation_event_fixture() as data:
            statement = _statement(data, direction=BankMovementDirection.DEBIT)
            await _persist_statement(data, statement)
            payable_id, installment_id = await _seed_scheduled_payable(data)
            async with data.database.session() as session, session.begin():
                await session.execute(
                    update(PayableModel)
                    .where(PayableModel.id == payable_id)
                    .values(status="PAID", version=2, updated_by=data.actor_id)
                )
                await session.execute(
                    update(PayableInstallmentModel)
                    .where(PayableInstallmentModel.id == installment_id)
                    .values(
                        status="PAID",
                        paid_on=date(2026, 10, 28),
                        payment_reference="DOC-184",
                        updated_by=data.actor_id,
                    )
                )
            event = _event(
                data,
                message_type="PaymentBatchConfirmed",
                producer_domain="treasury",
                aggregate_type="payment_batch",
                aggregate_id=uuid4(),
            )
            consumer = BankReconciliationEventConsumer(data.database)
            first = await consumer.consume(event)
            replay = await consumer.consume(event)
            assert first.processed is True
            assert replay.duplicate is True

            async with data.database.session() as session:
                persisted = await BankStatementRepository(session, company_id=data.company_id).get(
                    statement.id
                )
                assert persisted is not None
                assert persisted.version == 2
                assert persisted.movements[0].status is BankMovementStatus.RECONCILED
                assert persisted.movements[0].matched_reference_id == installment_id
                assert await _count_outbox(session, statement.movements[0].id) == 1
                assert await _processed_inbox(session) == 1

    asyncio.run(scenario())


def test_receivable_event_projects_credit_candidate_and_reconciles_reactively() -> None:
    async def scenario() -> None:
        async with reconciliation_event_fixture() as data:
            statement = _statement(data, direction=BankMovementDirection.CREDIT)
            await _persist_statement(data, statement)
            reference_id = uuid4()
            event = _event(
                data,
                message_type="ReceivableInstallmentSettled",
                producer_domain="receivables",
                aggregate_type="receivable_installment",
                aggregate_id=reference_id,
                payload={
                    "reference_id": str(reference_id),
                    "settled_on": "2026-10-28",
                    "amount": "100.00",
                    "document_number": "DOC-184",
                },
            )
            assert (await BankReconciliationEventConsumer(data.database).consume(event)).processed

            async with data.database.session() as session:
                projected = await session.get(BankReconciliationCandidateModel, reference_id)
                persisted = await BankStatementRepository(session, company_id=data.company_id).get(
                    statement.id
                )
                assert projected is not None
                assert projected.source == BankCandidateSource.RECEIVABLE_M13.value
                assert projected.active is True
                assert persisted is not None
                assert persisted.movements[0].matched_reference_id == reference_id
                outbox = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.aggregate_id == statement.movements[0].id,
                        OutboxEventModel.event_type == BANK_MOVEMENT_RECONCILED,
                    )
                )
                assert outbox is not None
                assert outbox.causation_id == event.message_id

    asyncio.run(scenario())


def test_reversal_resolves_prior_ambiguity_and_marks_existing_matches_for_review() -> None:
    async def scenario() -> None:
        async with reconciliation_event_fixture() as data:
            ambiguous = _statement(data, direction=BankMovementDirection.CREDIT)
            matched = _statement(
                data,
                direction=BankMovementDirection.CREDIT,
                document_number="REV-184",
            )
            await _persist_statement(data, ambiguous)
            await _persist_statement(data, matched)
            kept_id = uuid4()
            reversed_id = uuid4()
            async with data.database.session() as session, session.begin():
                session.add_all(
                    [
                        _candidate(data, kept_id, document_number="DOC-184"),
                        _candidate(data, reversed_id, document_number="DOC-184"),
                    ]
                )
                repository = BankStatementRepository(session, company_id=data.company_id)
                current = await repository.get(matched.id)
                assert current is not None
                reconciled = current.apply(
                    ReconciliationDecision(
                        movement_id=current.movements[0].id,
                        status=ReconciliationStatus.MATCHED,
                        reason=ReconciliationReason.MATCHED,
                        candidate_id=reversed_id,
                        score=Decimal("1.0000"),
                    ),
                    reconciled_at=datetime(2026, 10, 28, 12, tzinfo=UTC),
                )
                await repository.save(reconciled, actor_id=data.actor_id)
                ambiguous_result = await BankConciliationService(
                    repository,
                    EventBankCandidateProvider(session, company_id=data.company_id),
                ).simulate(ambiguous.id)
                assert ambiguous_result.outcomes[0].classification is (
                    BankConciliationClassification.AMBIGUOUS
                )
            consumer = BankReconciliationEventConsumer(data.database)
            reversal = _event(
                data,
                message_type="ReceivableSettlementReversed",
                producer_domain="receivables",
                aggregate_type="receivable_installment",
                aggregate_id=reversed_id,
                aggregate_version=2,
                payload={"reference_id": str(reversed_id)},
            )
            await consumer.consume(reversal)

            async with data.database.session() as session:
                resolved = await BankStatementRepository(session, company_id=data.company_id).get(
                    ambiguous.id
                )
                immutable = await BankStatementRepository(session, company_id=data.company_id).get(
                    matched.id
                )
                candidate = await session.get(BankReconciliationCandidateModel, reversed_id)
                reviews = tuple(
                    await session.scalars(
                        select(OutboxEventModel).where(
                            OutboxEventModel.event_type == BANK_RECONCILIATION_REVIEW_REQUIRED,
                            OutboxEventModel.causation_id == reversal.message_id,
                        )
                    )
                )
                assert resolved is not None
                assert resolved.movements[0].matched_reference_id == kept_id
                assert immutable is not None
                assert immutable.movements[0].matched_reference_id == reversed_id
                assert candidate is not None
                assert candidate.active is False
                assert len(reviews) == 1
                assert reviews[0].payload["payload"]["matched_reference_id"] == str(reversed_id)

    asyncio.run(scenario())


def test_concurrent_out_of_order_events_keep_monotonic_candidate_and_inbox() -> None:
    async def scenario() -> None:
        async with reconciliation_event_fixture() as data:
            statement = _statement(data, direction=BankMovementDirection.CREDIT)
            await _persist_statement(data, statement)
            reference_id = uuid4()
            now = datetime.now(UTC)
            low = _event(
                data,
                message_type="ReceivableInstallmentSettled",
                producer_domain="receivables",
                aggregate_type="receivable_installment",
                aggregate_id=reference_id,
                aggregate_version=2,
                occurred_at=now + timedelta(seconds=2),
                payload={
                    "reference_id": str(reference_id),
                    "settled_on": "2026-10-28",
                    "amount": "999.00",
                    "document_number": "OLD-184",
                },
            )
            high = _event(
                data,
                message_type="ReceivableInstallmentSettled",
                producer_domain="receivables",
                aggregate_type="receivable_installment",
                aggregate_id=reference_id,
                aggregate_version=3,
                occurred_at=now,
                payload={
                    "reference_id": str(reference_id),
                    "settled_on": "2026-10-28",
                    "amount": "100.00",
                    "document_number": "DOC-184",
                },
            )
            consumer = BankReconciliationEventConsumer(data.database)
            results = await asyncio.gather(consumer.consume(low), consumer.consume(high))
            assert all(value.processed for value in results)

            async with data.database.session() as session:
                cursor = await session.get(
                    BankReconciliationSourceCursorModel,
                    (data.company_id, "finance", "receivable_installment", reference_id),
                )
                candidate = await session.get(BankReconciliationCandidateModel, reference_id)
                persisted = await BankStatementRepository(session, company_id=data.company_id).get(
                    statement.id
                )
                assert cursor is not None
                assert cursor.aggregate_version == 3
                assert candidate is not None
                assert candidate.source_version == 3
                assert candidate.amount == Decimal("100.0000")
                assert persisted is not None
                assert persisted.movements[0].matched_reference_id == reference_id
                assert await _processed_inbox(session) == 2

    asyncio.run(scenario())


def test_outbox_failure_rolls_back_inbox_cursor_candidate_and_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_enqueue(self: OutboxService, *_: object, **__: object) -> UUID:
        del self
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(OutboxService, "enqueue", fail_enqueue)

    async def scenario() -> None:
        async with reconciliation_event_fixture() as data:
            statement = _statement(data, direction=BankMovementDirection.CREDIT)
            await _persist_statement(data, statement)
            reference_id = uuid4()
            event = _event(
                data,
                message_type="ReceivableInstallmentSettled",
                producer_domain="receivables",
                aggregate_type="receivable_installment",
                aggregate_id=reference_id,
                payload={
                    "reference_id": str(reference_id),
                    "settled_on": "2026-10-28",
                    "amount": "100.00",
                    "document_number": "DOC-184",
                },
            )
            with pytest.raises(RuntimeError, match="outbox unavailable"):
                await BankReconciliationEventConsumer(data.database).consume(event)

            async with data.database.session() as session:
                persisted = await BankStatementRepository(session, company_id=data.company_id).get(
                    statement.id
                )
                counts = [
                    await session.scalar(
                        select(func.count())
                        .select_from(InboxEventModel)
                        .where(InboxEventModel.consumer_name == BANK_RECONCILIATION_EVENT_CONSUMER)
                    ),
                    await session.scalar(
                        select(func.count())
                        .select_from(BankReconciliationSourceCursorModel)
                        .where(BankReconciliationSourceCursorModel.company_id == data.company_id)
                    ),
                    await session.scalar(
                        select(func.count())
                        .select_from(BankReconciliationCandidateModel)
                        .where(BankReconciliationCandidateModel.company_id == data.company_id)
                    ),
                ]
                assert persisted == statement
                assert counts == [0, 0, 0]

    asyncio.run(scenario())


def test_consumer_rejects_cross_tenant_payload_before_inbox() -> None:
    async def scenario() -> None:
        async with reconciliation_event_fixture() as data:
            event = _event(
                data,
                message_type="ReceivableInstallmentSettled",
                producer_domain="receivables",
                aggregate_type="receivable_installment",
                aggregate_id=uuid4(),
                payload={
                    "company_id": str(data.other_company_id),
                    "settled_on": "2026-10-28",
                    "amount": "100.00",
                },
            )
            with pytest.raises(ValueError, match="company boundary"):
                await BankReconciliationEventConsumer(data.database).consume(event)
            async with data.database.session() as session:
                assert await _processed_inbox(session) == 0

    asyncio.run(scenario())


def test_migration_0047_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        from erp.platform.database import Database

        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    tables = set(inspect(sync_connection).get_table_names(schema="finance"))
                    event_tables = {
                        "bank_reconciliation_source_cursor",
                        "bank_reconciliation_candidate",
                    }
                    assert event_tables.issubset(tables) is expected

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    command.downgrade(configuration, "0046")
    asyncio.run(verify(False))
    command.upgrade(configuration, "0047")
    asyncio.run(verify(True))


def _candidate(
    data: ProcurementFixture,
    reference_id: UUID,
    *,
    document_number: str,
) -> BankReconciliationCandidateModel:
    return BankReconciliationCandidateModel(
        id=reference_id,
        company_id=data.company_id,
        source=BankCandidateSource.RECEIVABLE_M13.value,
        expected_on=date(2026, 10, 28),
        amount=Decimal("100.00"),
        direction=BankMovementDirection.CREDIT.value,
        document_number=document_number,
        active=True,
        source_version=1,
        source_event_id=uuid4(),
        source_occurred_at=datetime(2026, 10, 28, tzinfo=UTC),
    )


async def _count_outbox(session: object, aggregate_id: UUID) -> int:
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(session, AsyncSession)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(OutboxEventModel)
            .where(
                OutboxEventModel.aggregate_id == aggregate_id,
                OutboxEventModel.event_type == BANK_MOVEMENT_RECONCILED,
            )
        )
        or 0
    )


async def _processed_inbox(session: object) -> int:
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(session, AsyncSession)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(InboxEventModel)
            .where(
                InboxEventModel.consumer_name == BANK_RECONCILIATION_EVENT_CONSUMER,
                InboxEventModel.status == InboxStatus.PROCESSED,
            )
        )
        or 0
    )


__all__: list[str] = []
