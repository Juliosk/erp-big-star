"""M12 bank-statement persistence integration against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect, text, update
from sqlalchemy.exc import DBAPIError

from erp.modules.finance.domain import (
    BankMovement,
    BankMovementDirection,
    BankMovementStatus,
    BankStatement,
    BankStatementConflictError,
    BankStatementSource,
    BankTransactionKind,
    FinanceScopeError,
    FinanceVersionConflictError,
    ReconciliationDecision,
    ReconciliationReason,
    ReconciliationStatus,
)
from erp.modules.finance.infrastructure import (
    BankStatementModel,
    BankStatementRepository,
    ConciliationRecordModel,
    StatementImportAuditModel,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_payable_repository import finance_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


@asynccontextmanager
async def bank_statement_fixture() -> AsyncIterator[ProcurementFixture]:
    async with finance_fixture() as data:
        companies = (data.company_id, data.other_company_id)
        try:
            yield data
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    text("SET LOCAL erp.allow_bank_reconciliation_audit_cleanup = 'on'")
                )
                await session.execute(
                    delete(BankStatementModel).where(
                        BankStatementModel.company_id.in_(companies)
                    )
                )


def _statement(
    data: ProcurementFixture,
    *,
    company_id: UUID | None = None,
    statement_id: UUID | None = None,
    bank_account_id: UUID | None = None,
    source_hash: str = "a" * 64,
) -> BankStatement:
    tenant = company_id or data.company_id
    account_id = bank_account_id or uuid4()
    return BankStatement(
        id=statement_id or uuid4(),
        company_id=tenant,
        bank_account_id=account_id,
        bank_code="001",
        account_reference="AG 1234 / CC 98765-0",
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        imported_at=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
        source=BankStatementSource.OFX,
        source_hash=source_hash,
        movements=(
            BankMovement(
                id=uuid4(),
                company_id=tenant,
                bank_account_id=account_id,
                external_id="FITID-181-1",
                booked_on=date(2026, 10, 10),
                amount=Decimal("125.40"),
                direction=BankMovementDirection.DEBIT,
                kind=BankTransactionKind.PAYMENT,
                description="Pagamento fornecedor",
                document_number="PAY-181",
            ),
            BankMovement(
                id=uuid4(),
                company_id=tenant,
                bank_account_id=account_id,
                external_id="FITID-181-2",
                booked_on=date(2026, 10, 11),
                amount=Decimal("5.00"),
                direction=BankMovementDirection.DEBIT,
                kind=BankTransactionKind.BANK_FEE,
                description="Tarifa bancaria",
            ),
        ),
    )


def test_round_trip_movements_import_audit_and_append_only_conciliation() -> None:
    async def scenario() -> None:
        async with bank_statement_fixture() as data:
            statement = _statement(data)
            async with data.database.session() as session, session.begin():
                repository = BankStatementRepository(session, company_id=data.company_id)
                await repository.add(
                    statement,
                    actor_id=data.actor_id,
                    original_file_name="extrato-outubro.ofx",
                    file_size_bytes=2048,
                )
                assert await repository.get(statement.id) == statement
                assert await repository.get_by_hash(
                    bank_account_id=statement.bank_account_id,
                    source_hash=statement.source_hash.upper(),
                ) == statement
                assert await repository.list(
                    bank_account_id=statement.bank_account_id,
                    period_from=date(2026, 10, 1),
                    period_to=date(2026, 10, 31),
                ) == (statement,)
                audit = await repository.import_audit(statement.id)
                assert audit is not None
                assert audit.movement_count == 2
                assert audit.source_hash == statement.source_hash

                decision = ReconciliationDecision(
                    movement_id=statement.movements[0].id,
                    status=ReconciliationStatus.MATCHED,
                    reason=ReconciliationReason.MATCHED,
                    candidate_id=uuid4(),
                    score=Decimal("0.9500"),
                )
                reconciled = statement.apply(
                    decision,
                    reconciled_at=datetime(2026, 10, 28, 12, 5, tzinfo=UTC),
                )
                await repository.save(reconciled, actor_id=data.actor_id)
                loaded = await repository.get(statement.id)
                assert loaded == reconciled
                assert loaded is not None
                assert loaded.movements[0].status is BankMovementStatus.RECONCILED
                records = await repository.conciliations(statement.id)
                assert len(records) == 1
                assert records[0].matched_reference_id == decision.candidate_id

                savepoint = await session.begin_nested()
                with pytest.raises(DBAPIError, match="append-only"):
                    await session.execute(
                        update(ConciliationRecordModel)
                        .where(ConciliationRecordModel.id == records[0].id)
                        .values(details={"tampered": True})
                    )
                await savepoint.rollback()
                savepoint = await session.begin_nested()
                with pytest.raises(DBAPIError, match="append-only"):
                    await session.execute(
                        update(StatementImportAuditModel)
                        .where(StatementImportAuditModel.id == audit.id)
                        .values(details={"tampered": True})
                    )
                await savepoint.rollback()

    asyncio.run(scenario())


def test_duplicate_hash_is_idempotent_identity_and_scope_is_tenant_bound() -> None:
    async def scenario() -> None:
        async with bank_statement_fixture() as data:
            account_id = uuid4()
            own = _statement(data, bank_account_id=account_id)
            duplicate = _statement(data, bank_account_id=account_id, source_hash=own.source_hash)
            foreign = _statement(
                data,
                company_id=data.other_company_id,
                bank_account_id=account_id,
                source_hash=own.source_hash,
            )
            async with data.database.session() as session, session.begin():
                repository = BankStatementRepository(session, company_id=data.company_id)
                other_repository = BankStatementRepository(
                    session, company_id=data.other_company_id
                )
                await repository.add(
                    own,
                    actor_id=data.actor_id,
                    original_file_name="same.ofx",
                    file_size_bytes=100,
                )
                savepoint = await session.begin_nested()
                with pytest.raises(BankStatementConflictError):
                    await repository.add(
                        duplicate,
                        actor_id=data.actor_id,
                        original_file_name="same-copy.ofx",
                        file_size_bytes=100,
                    )
                await savepoint.rollback()
                assert await repository.get_by_hash(
                    bank_account_id=account_id,
                    source_hash=own.source_hash,
                ) == own
                assert await other_repository.get(own.id) is None
                with pytest.raises(FinanceScopeError):
                    await other_repository.add(
                        own,
                        actor_id=data.actor_id,
                        original_file_name="foreign.ofx",
                        file_size_bytes=100,
                    )
                await other_repository.add(
                    foreign,
                    actor_id=data.actor_id,
                    original_file_name="foreign.ofx",
                    file_size_bytes=100,
                )
                assert await other_repository.get_by_hash(
                    bank_account_id=account_id,
                    source_hash=own.source_hash,
                ) == foreign

    asyncio.run(scenario())


def test_optimistic_lock_and_repository_contract_validation() -> None:
    async def scenario() -> None:
        async with bank_statement_fixture() as data:
            statement = _statement(data)
            async with data.database.session() as session, session.begin():
                with pytest.raises(ValueError, match="company UUID"):
                    BankStatementRepository(session, company_id=UUID(int=0))
                repository = BankStatementRepository(session, company_id=data.company_id)
                with pytest.raises(TypeError, match="BankStatement"):
                    await repository.add(
                        object(),  # type: ignore[arg-type]
                        actor_id=data.actor_id,
                        original_file_name=None,
                        file_size_bytes=0,
                    )
                with pytest.raises(ValueError, match="file_size_bytes"):
                    await repository.add(
                        statement,
                        actor_id=data.actor_id,
                        original_file_name=None,
                        file_size_bytes=-1,
                    )
                await repository.add(
                    statement,
                    actor_id=data.actor_id,
                    original_file_name=None,
                    file_size_bytes=0,
                )
                decision = ReconciliationDecision(
                    movement_id=statement.movements[0].id,
                    status=ReconciliationStatus.MATCHED,
                    reason=ReconciliationReason.MATCHED,
                    candidate_id=uuid4(),
                    score=Decimal("1.0000"),
                )
                reconciled = statement.apply(
                    decision,
                    reconciled_at=datetime(2026, 10, 28, 12, 5, tzinfo=UTC),
                )
                await repository.save(reconciled, actor_id=data.actor_id)
                with pytest.raises(FinanceVersionConflictError):
                    await repository.save(
                        reconciled,
                        actor_id=data.actor_id,
                        expected_version=1,
                    )
                with pytest.raises(ValueError, match="limit"):
                    await repository.list(limit=0)
                with pytest.raises(ValueError, match="offset"):
                    await repository.list(offset=-1)
                with pytest.raises(ValueError, match="period_from"):
                    await repository.list(
                        period_from=date(2026, 11, 1),
                        period_to=date(2026, 10, 1),
                    )

    asyncio.run(scenario())


def test_migration_0046_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="finance"))
                    reconciliation_tables = {
                        "bank_statement",
                        "bank_movement",
                        "statement_import_audit",
                        "conciliation_record",
                    }
                    assert reconciliation_tables.issubset(tables) is expected
                    if not expected:
                        return
                    uniques = {
                        value["name"]
                        for value in inspector.get_unique_constraints(
                            "bank_statement", schema="finance"
                        )
                    }
                    assert "uq_bank_statement_company_account_hash" in uniques
                    movement_fks = inspector.get_foreign_keys(
                        "bank_movement", schema="finance"
                    )
                    assert any(
                        value["constrained_columns"]
                        == ["company_id", "bank_statement_id"]
                        for value in movement_fks
                    )
                    indexes = {
                        value["name"]
                        for value in inspector.get_indexes(
                            "bank_statement", schema="finance"
                        )
                    }
                    assert "ix_bank_statement_company_account_period" in indexes

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0045")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0046")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")
