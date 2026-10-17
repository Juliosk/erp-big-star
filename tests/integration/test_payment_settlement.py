"""M12 bank-confirmed settlement and rejection/reversal integration coverage."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import (
    PAYMENT_BATCH_CONFIRMED,
    PAYMENT_BATCH_FAILED,
    PAYMENT_BATCH_SUBMITTED,
    PaymentSettlementService,
    SubmitPaymentBatch,
    TreasuryCommandMetadata,
)
from erp.modules.finance.domain import (
    PayableInstallmentStatus,
    PayableStatus,
    PaymentBatch,
    PaymentBatchStatus,
    TreasurySegregationPolicy,
)
from erp.modules.finance.infrastructure import (
    Cnab240ReturnParser,
    PayableRepository,
    PaymentBatchRepository,
    PostgresPaymentBatchEventPublisher,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_treasury_repository import TreasuryFixture, treasury_fixture

pytestmark = pytest.mark.integration


def test_bank_confirmation_is_the_only_settlement_trigger() -> None:
    async def scenario() -> None:
        async with treasury_fixture() as fixture:
            data = fixture.matching.data
            submitted_at = datetime(2026, 12, 9, 12, 0, tzinfo=UTC)
            metadata = TreasuryCommandMetadata.new()
            async with data.database.session() as session, session.begin():
                batches = PaymentBatchRepository(session, company_id=data.company_id)
                payables = PayableRepository(session, company_id=data.company_id)
                released = await _persist_released(batches, fixture)
                service = PaymentSettlementService(
                    batches,
                    payables,
                    PostgresPaymentBatchEventPublisher(session),
                )

                submitted = await service.record_submission(
                    SubmitPaymentBatch(
                        company_id=data.company_id,
                        payment_batch_id=released.id,
                        expected_version=released.version,
                        protocol="REM-175-CONFIRMED",
                        occurred_at=submitted_at,
                        metadata=metadata,
                    ),
                    actor_id=fixture.batch_executor,
                )
                assert submitted.batch.status is PaymentBatchStatus.SUBMITTED
                assert submitted.payables[0].status is PayableStatus.SCHEDULED
                assert (
                    submitted.payables[0].installments[0].status
                    is PayableInstallmentStatus.SCHEDULED
                )

                notification = (
                    Cnab240ReturnParser()
                    .parse(
                        _cnab_return(
                            batch_id=released.id,
                            protocol="BANK-175-CONFIRMED",
                            status="00",
                            amount_cents=12540,
                        ),
                        company_id=data.company_id,
                    )
                    .records[0]
                )
                result = await service.process(
                    notification,
                    actor_id=fixture.batch_executor,
                    metadata=metadata,
                )

                assert result.batch.status is PaymentBatchStatus.CONFIRMED
                assert result.batch.bank_confirmation is not None
                assert result.payables[0].status is PayableStatus.PAID
                installment = result.payables[0].installments[0]
                assert installment.status is PayableInstallmentStatus.PAID
                assert installment.payment_reference == "BANK-175-CONFIRMED"

                replay = await service.process(
                    notification,
                    actor_id=fixture.batch_executor,
                    metadata=metadata,
                )
                assert replay.replayed is True
                assert replay.event_id is None

                audit = await batches.audit_log(released.id)
                assert [entry.to_status for entry in audit][-2:] == [
                    "SUBMITTED",
                    "CONFIRMED",
                ]
                events = await _event_types(session, released.id)
                assert PAYMENT_BATCH_SUBMITTED in events
                assert PAYMENT_BATCH_CONFIRMED in events

    asyncio.run(scenario())


@pytest.mark.parametrize("status", ["AG", "99"])
def test_bank_rejection_or_failure_releases_installment_for_rescheduling(status: str) -> None:
    async def scenario() -> None:
        async with treasury_fixture() as fixture:
            data = fixture.matching.data
            metadata = TreasuryCommandMetadata.new()
            async with data.database.session() as session, session.begin():
                batches = PaymentBatchRepository(session, company_id=data.company_id)
                payables = PayableRepository(session, company_id=data.company_id)
                released = await _persist_released(batches, fixture)
                service = PaymentSettlementService(
                    batches,
                    payables,
                    PostgresPaymentBatchEventPublisher(session),
                )
                await service.record_submission(
                    SubmitPaymentBatch(
                        data.company_id,
                        released.id,
                        released.version,
                        "REM-175-FAILED",
                        datetime(2026, 12, 9, 12, 0, tzinfo=UTC),
                        metadata,
                    ),
                    actor_id=fixture.batch_executor,
                )
                notification = (
                    Cnab240ReturnParser()
                    .parse(
                        _cnab_return(
                            batch_id=released.id,
                            protocol=f"BANK-175-{status}",
                            status=status,
                            amount_cents=0,
                            reason="Invalid beneficiary account",
                        ),
                        company_id=data.company_id,
                    )
                    .records[0]
                )

                result = await service.process(
                    notification,
                    actor_id=fixture.batch_executor,
                    metadata=metadata,
                )

                assert result.batch.status is PaymentBatchStatus.FAILED
                assert result.batch.bank_failure is not None
                assert result.batch.bank_failure.status_code == status
                assert result.payables[0].status is PayableStatus.APPROVED
                installment = result.payables[0].installments[0]
                assert installment.status is PayableInstallmentStatus.OPEN
                assert installment.schedule_id is None
                assert installment.payment_reference is None
                assert PAYMENT_BATCH_FAILED in await _event_types(session, released.id)

    asyncio.run(scenario())


def test_migration_0044_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    columns = {
                        value["name"]
                        for value in inspector.get_columns("payment_batch", schema="finance")
                    }
                    failure_columns = {
                        "bank_failure_kind",
                        "bank_failure_protocol",
                        "bank_failure_status",
                        "bank_failed_at",
                        "bank_failure_reason",
                    }
                    assert failure_columns.issubset(columns) is expected

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0043")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0044")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")


async def _persist_released(
    repository: PaymentBatchRepository,
    fixture: TreasuryFixture,
) -> PaymentBatch:
    batch = fixture.batch
    creator = fixture.batch_creator
    approver = fixture.batch_approver
    executor = fixture.batch_executor
    await repository.add(batch, actor_id=creator)
    pending = batch.submit_for_approval()
    await repository.save(pending, actor_id=creator)
    approved = pending.approve(actor_id=approver, policy=TreasurySegregationPolicy())
    await repository.save(approved, actor_id=approver)
    released = approved.release(actor_id=executor, policy=TreasurySegregationPolicy())
    await repository.save(released, actor_id=executor)
    return released


async def _event_types(session: AsyncSession, batch_id: UUID) -> set[str]:
    events = tuple(
        await session.scalars(
            select(OutboxEventModel).where(OutboxEventModel.aggregate_id == batch_id)
        )
    )
    return {event.event_type for event in events}


def _cnab_return(
    *,
    batch_id: UUID,
    protocol: str,
    status: str,
    amount_cents: int,
    reason: str = "",
) -> bytes:
    width = 240
    header = "0SETTLEMENT-175".ljust(width)
    detail = (
        f"3{batch_id.hex}{protocol:<40}{status:<2}{amount_cents:018d}20261210{reason:<80}"
    ).ljust(width)
    trailer = "9".ljust(width)
    return f"{header}\n{detail}\n{trailer}".encode("ascii")
