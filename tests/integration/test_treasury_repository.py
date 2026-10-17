"""M12 Treasury repository integration against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect, text, update
from sqlalchemy.exc import DBAPIError

from erp.modules.finance.domain import (
    BankAccountType,
    BankPaymentConfirmation,
    BankRemittanceFormat,
    BeneficiaryBankAccount,
    InvalidTreasuryRuleError,
    MatchingGateStatus,
    Payable,
    PayableInstallmentPaymentSnapshot,
    PayableSegregationPolicy,
    PaymentBatch,
    PaymentBatchItem,
    PaymentBatchStatus,
    PaymentEligibilityPolicy,
    PaymentExecutionMode,
    TreasuryConflictError,
    TreasuryScopeError,
    TreasurySegregationPolicy,
    TreasuryVersionConflictError,
)
from erp.modules.finance.infrastructure import (
    BatchAuditLogModel,
    PayableInstallmentModel,
    PayableModel,
    PayableRepository,
    PaymentBatchModel,
    PaymentBatchRepository,
)
from erp.modules.procurement.infrastructure import ThreeWayMatchRepository
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_matching_repository import MatchingFixture, matching_fixture

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class TreasuryFixture:
    matching: MatchingFixture
    batch: PaymentBatch
    batch_creator: UUID
    batch_approver: UUID
    batch_executor: UUID


@asynccontextmanager
async def treasury_fixture() -> AsyncIterator[TreasuryFixture]:
    async with matching_fixture() as matching:
        data = matching.data
        source = matching.aggregate
        payable_creator = uuid4()
        payable_approver = uuid4()
        payable = Payable.create(
            company_id=data.company_id,
            number=f"TREASURY-{uuid4().hex[:10].upper()}",
            supplier_id=source.purchase_order_snapshot.supplier_id,
            supplier_tax_id="12345678000195",
            created_by=payable_creator,
            provisional_entry_id=source.financial_snapshot.provisional_entry.id,
            nominal_amount=Decimal("125.40"),
            installment_plan=((date(2026, 12, 10), Decimal("125.40")),),
        )
        pending_payable = payable.submit_for_approval()
        approved_payable = pending_payable.approve(
            approver_id=payable_approver,
            policy=PayableSegregationPolicy(Decimal("1.00")),
        )
        async with data.database.session() as session, session.begin():
            payables = PayableRepository(session, company_id=data.company_id)
            await payables.add(payable, actor_id=payable_creator)
            await payables.save(pending_payable, actor_id=payable_creator)
            await payables.save(approved_payable, actor_id=payable_approver)

            matching_repository = ThreeWayMatchRepository(session, company_id=data.company_id)
            await matching_repository.add(source, actor_id=data.actor_id)
            running = source.start(occurred_at=source.created_at)
            await matching_repository.save(running, actor_id=data.actor_id)
            matched = running.evaluate(occurred_at=running.started_at)
            await matching_repository.save(matched, actor_id=data.actor_id)

        batch_id = uuid4()
        installment = approved_payable.installments[0]
        candidate = PayableInstallmentPaymentSnapshot(
            company_id=data.company_id,
            payable_id=approved_payable.id,
            installment_id=installment.id,
            supplier_id=approved_payable.supplier_id,
            amount=installment.amount,
            currency=approved_payable.currency,
            due_date=installment.due_date,
            payable_status=approved_payable.status,
            installment_status=installment.status,
            matching_status=MatchingGateStatus.MATCHED,
            matching_session_id=matched.id,
            payable_created_by=approved_payable.created_by,
            payable_approved_by=payable_approver,
            beneficiary=BeneficiaryBankAccount(
                bank_code="001",
                branch_number="1234",
                account_number="987654",
                account_digit="X",
                account_type=BankAccountType.CHECKING,
                holder_name="Fornecedor Treasury",
                holder_tax_id="12345678000195",
            ),
        )
        item = PaymentBatchItem.from_snapshot(
            item_id=uuid4(),
            batch_id=batch_id,
            snapshot=candidate,
            policy=PaymentEligibilityPolicy(),
        )
        batch_creator = uuid4()
        fixture = TreasuryFixture(
            matching=matching,
            batch=PaymentBatch(
                id=batch_id,
                company_id=data.company_id,
                code=f"BATCH-{uuid4().hex[:10].upper()}",
                treasury_account_id=uuid4(),
                scheduled_date=date(2026, 12, 9),
                created_by=batch_creator,
                remittance_format=BankRemittanceFormat.CNAB_240,
                execution_mode=PaymentExecutionMode.DRY_RUN,
                items=(item,),
            ),
            batch_creator=batch_creator,
            batch_approver=uuid4(),
            batch_executor=uuid4(),
        )
        try:
            yield fixture
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(text("SET LOCAL erp.allow_treasury_audit_cleanup = 'on'"))
                await session.execute(
                    delete(PaymentBatchModel).where(PaymentBatchModel.company_id == data.company_id)
                )
                await session.execute(
                    delete(PayableInstallmentModel).where(
                        PayableInstallmentModel.payable_id == approved_payable.id
                    )
                )
                await session.execute(
                    delete(PayableModel).where(PayableModel.id == approved_payable.id)
                )


def test_payment_batch_round_trip_state_machine_items_and_append_only_audit() -> None:
    async def scenario() -> None:
        async with treasury_fixture() as fixture:
            data = fixture.matching.data
            policy = TreasurySegregationPolicy()
            async with data.database.session() as session, session.begin():
                repository = PaymentBatchRepository(session, company_id=data.company_id)
                await repository.add(fixture.batch, actor_id=fixture.batch_creator)
                assert await repository.get(fixture.batch.id) == fixture.batch
                assert await repository.list(status=PaymentBatchStatus.DRAFT) == (fixture.batch,)

                pending = fixture.batch.submit_for_approval()
                await repository.save(pending, actor_id=fixture.batch_creator)
                approved = pending.approve(
                    actor_id=fixture.batch_approver,
                    policy=policy,
                )
                await repository.save(approved, actor_id=fixture.batch_approver)
                released = approved.release(
                    actor_id=fixture.batch_executor,
                    policy=policy,
                )
                await repository.save(released, actor_id=fixture.batch_executor)
                submitted_at = datetime.now(UTC)
                submitted = released.mark_submitted(
                    protocol="BANK-REM-173",
                    occurred_at=submitted_at,
                )
                await repository.save(submitted, actor_id=fixture.batch_executor)
                confirmed = submitted.confirm(
                    BankPaymentConfirmation(
                        protocol="BANK-RET-173",
                        status_code="PAID",
                        confirmed_at=submitted_at + timedelta(minutes=1),
                        confirmed_amount=submitted.total_amount,
                    )
                )
                await repository.save(confirmed, actor_id=fixture.batch_executor)

                assert await repository.get(fixture.batch.id) == confirmed
                audit = await repository.audit_log(fixture.batch.id)
                assert [value.aggregate_version for value in audit] == [1, 2, 3, 4, 5, 6]
                assert [(value.from_status, value.to_status) for value in audit] == [
                    (None, "DRAFT"),
                    ("DRAFT", "PENDING_APPROVAL"),
                    ("PENDING_APPROVAL", "APPROVED"),
                    ("APPROVED", "RELEASED"),
                    ("RELEASED", "SUBMITTED"),
                    ("SUBMITTED", "CONFIRMED"),
                ]

                savepoint = await session.begin_nested()
                with pytest.raises(DBAPIError, match="append-only"):
                    await session.execute(
                        update(BatchAuditLogModel)
                        .where(BatchAuditLogModel.id == audit[0].id)
                        .values(details={"tampered": True})
                    )
                await savepoint.rollback()

    asyncio.run(scenario())


def test_repository_is_tenant_bound_and_translates_identity_and_version_conflicts() -> None:
    async def scenario() -> None:
        async with treasury_fixture() as fixture:
            data = fixture.matching.data
            async with data.database.session() as session, session.begin():
                repository = PaymentBatchRepository(session, company_id=data.company_id)
                await repository.add(fixture.batch, actor_id=fixture.batch_creator)
                foreign = PaymentBatchRepository(session, company_id=data.other_company_id)
                assert await foreign.get(fixture.batch.id) is None
                with pytest.raises(TreasuryScopeError):
                    await foreign.add(fixture.batch, actor_id=fixture.batch_creator)

                duplicate_id = uuid4()
                duplicate = replace(
                    fixture.batch,
                    id=duplicate_id,
                    items=(
                        replace(
                            fixture.batch.items[0],
                            id=uuid4(),
                            batch_id=duplicate_id,
                        ),
                    ),
                )
                savepoint = await session.begin_nested()
                with pytest.raises(TreasuryConflictError):
                    await repository.add(duplicate, actor_id=fixture.batch_creator)
                await savepoint.rollback()

                pending = fixture.batch.submit_for_approval()
                await repository.save(pending, actor_id=fixture.batch_creator)
                with pytest.raises(TreasuryVersionConflictError):
                    await repository.save(
                        pending,
                        actor_id=fixture.batch_creator,
                        expected_version=1,
                    )

    asyncio.run(scenario())


def test_repository_rejects_snapshot_drift_invalid_transitions_and_contract_inputs() -> None:
    async def scenario() -> None:
        async with treasury_fixture() as fixture:
            data = fixture.matching.data
            async with data.database.session() as session, session.begin():
                with pytest.raises(ValueError, match="company UUID"):
                    PaymentBatchRepository(session, company_id=UUID(int=0))
                repository = PaymentBatchRepository(session, company_id=data.company_id)
                with pytest.raises(TypeError, match="PaymentBatch"):
                    await repository.add(object(), actor_id=fixture.batch_creator)  # type: ignore[arg-type]
                with pytest.raises(ValueError, match="actor UUID"):
                    await repository.add(fixture.batch, actor_id=UUID(int=0))
                with pytest.raises(ValueError, match="start draft"):
                    await repository.add(
                        fixture.batch.submit_for_approval(),
                        actor_id=fixture.batch_creator,
                    )
                await repository.add(fixture.batch, actor_id=fixture.batch_creator)
                pending = fixture.batch.submit_for_approval()
                with pytest.raises(InvalidTreasuryRuleError, match="immutable"):
                    await repository.save(
                        replace(pending, code="CHANGED-173"),
                        actor_id=fixture.batch_creator,
                    )
                with pytest.raises(InvalidTreasuryRuleError, match="not allowed"):
                    await repository.save(
                        replace(
                            fixture.batch,
                            status=PaymentBatchStatus.APPROVED,
                            approved_by=fixture.batch_approver,
                            version=2,
                        ),
                        actor_id=fixture.batch_approver,
                    )
                with pytest.raises(ValueError, match="version increment"):
                    await repository.save(fixture.batch, actor_id=fixture.batch_creator)
                with pytest.raises(ValueError, match="limit"):
                    await repository.list(limit=0)
                with pytest.raises(ValueError, match="offset"):
                    await repository.list(offset=-1)
                with pytest.raises(ValueError, match="official"):
                    await repository.list(status="DRAFT")  # type: ignore[arg-type]

    asyncio.run(scenario())


def test_migration_0043_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="finance"))
                    treasury_tables = {
                        "payment_batch",
                        "payment_batch_item",
                        "batch_audit_log",
                    }
                    assert treasury_tables.issubset(tables) is expected
                    installment_uniques = {
                        value["name"]
                        for value in inspector.get_unique_constraints(
                            "payable_installment", schema="finance"
                        )
                    }
                    assert (
                        "uq_payable_installment_company_payable_id"
                        in installment_uniques
                    ) is expected
                    if not expected:
                        return
                    batch_uniques = {
                        value["name"]
                        for value in inspector.get_unique_constraints(
                            "payment_batch", schema="finance"
                        )
                    }
                    assert "uq_payment_batch_company_code" in batch_uniques
                    item_fks = inspector.get_foreign_keys("payment_batch_item", schema="finance")
                    constrained = {tuple(value["constrained_columns"]) for value in item_fks}
                    assert ("company_id", "payment_batch_id") in constrained
                    assert ("company_id", "payable_id", "installment_id") in constrained
                    assert ("company_id", "matching_session_id") in constrained

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0042")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0043")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")
