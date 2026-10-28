"""Integration coverage for statement ingestion and automatic reconciliation."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.application import (
    BankCandidateSource,
    BankConciliationClassification,
    BankConciliationService,
    BankMatchCandidate,
    BankStatementIngestionService,
    CompositeBankCandidateProvider,
    IngestBankStatement,
)
from erp.modules.finance.domain import (
    BankMovement,
    BankMovementDirection,
    BankStatementSource,
    BankStatementStatus,
    BankTransactionKind,
    FinancialReconciliationCandidate,
    ReconciliationReason,
)
from erp.modules.finance.infrastructure import (
    BankStatementParserRegistry,
    BankStatementRepository,
    PayableBankCandidateProvider,
    PayableInstallmentModel,
    PayableModel,
)
from tests.integration.test_bank_statement_repository import bank_statement_fixture

pytestmark = pytest.mark.integration


class StaticCandidateProvider:
    def __init__(
        self,
        values: dict[str, tuple[BankMatchCandidate, ...]],
    ) -> None:
        self._values = values
        self.calls: list[str] = []

    async def candidates_for(
        self,
        movement: BankMovement,
    ) -> tuple[BankMatchCandidate, ...]:
        self.calls.append(movement.external_id)
        return self._values.get(movement.external_id, ())


def _csv(*rows: str) -> bytes:
    header = "data;valor;descricao;documento;id\n"
    return (header + "\n".join(rows) + "\n").encode()


def _command(
    *,
    company_id: UUID,
    bank_account_id: UUID,
    actor_id: UUID,
    content: bytes,
) -> IngestBankStatement:
    return IngestBankStatement(
        company_id=company_id,
        bank_account_id=bank_account_id,
        source=BankStatementSource.CSV,
        content=content,
        actor_id=actor_id,
        original_file_name="extrato-182.csv",
        bank_code="001",
        account_reference="1234/98765-0",
    )


def _candidate(
    movement: BankMovement,
    *,
    source: BankCandidateSource,
    expected_on: date | None = None,
    reference_id: UUID | None = None,
) -> BankMatchCandidate:
    return BankMatchCandidate(
        FinancialReconciliationCandidate(
            reference_id=reference_id or uuid4(),
            company_id=movement.company_id,
            expected_on=expected_on or movement.booked_on,
            amount=movement.amount,
            direction=movement.direction,
            document_number=movement.document_number,
        ),
        source,
    )


def test_identical_statement_ingestion_replays_by_sha256_without_duplicate_rows() -> None:
    async def scenario() -> None:
        async with bank_statement_fixture() as data:
            account_id = uuid4()
            content = _csv("28/10/2026;-100,00;Pagamento fornecedor;PAY-182;MOV-1")
            async with data.database.session() as session, session.begin():
                repository = BankStatementRepository(session, company_id=data.company_id)
                service = BankStatementIngestionService(
                    BankStatementParserRegistry(),
                    repository,
                    clock=lambda: datetime(2026, 10, 28, 13, tzinfo=UTC),
                )
                command = _command(
                    company_id=data.company_id,
                    bank_account_id=account_id,
                    actor_id=data.actor_id,
                    content=content,
                )
                first = await service.ingest(command)
                replay = await service.ingest(command)

                assert first.idempotency_replayed is False
                assert replay.idempotency_replayed is True
                assert replay.statement == first.statement
                assert await repository.list(bank_account_id=account_id) == (
                    first.statement,
                )
                audit = await repository.import_audit(first.statement.id)
                assert audit is not None
                assert audit.file_size_bytes == len(content)

    asyncio.run(scenario())


def test_auto_matching_reconciles_m12_debit_and_m13_credit_in_one_version() -> None:
    async def scenario() -> None:
        async with bank_statement_fixture() as data:
            content = _csv(
                "27/10/2026;-125,40;Pagamento fornecedor;PAY-182;M12-DEBIT",
                "28/10/2026;250,00;Recebimento cliente;REC-182;M13-CREDIT",
            )
            async with data.database.session() as session, session.begin():
                repository = BankStatementRepository(session, company_id=data.company_id)
                ingestion = BankStatementIngestionService(
                    BankStatementParserRegistry(),
                    repository,
                    clock=lambda: datetime(2026, 10, 28, 13, tzinfo=UTC),
                )
                imported = await ingestion.ingest(
                    _command(
                        company_id=data.company_id,
                        bank_account_id=uuid4(),
                        actor_id=data.actor_id,
                        content=content,
                    )
                )
                debit, credit = imported.statement.movements
                m12 = StaticCandidateProvider(
                    {debit.external_id: (_candidate(debit, source=BankCandidateSource.PAYABLE_M12),)}
                )
                m13 = StaticCandidateProvider(
                    {
                        credit.external_id: (
                            _candidate(credit, source=BankCandidateSource.RECEIVABLE_M13),
                        )
                    }
                )
                service = BankConciliationService(
                    repository,
                    CompositeBankCandidateProvider(m12, m13),
                )
                result = await service.reconcile(
                    imported.statement.id,
                    actor_id=data.actor_id,
                    occurred_at=datetime(2026, 10, 28, 13, 5, tzinfo=UTC),
                )

                assert result.statement.status is BankStatementStatus.RECONCILED
                assert result.statement.version == 2
                assert result.reconciled_count == 2
                assert [value.candidate_source for value in result.outcomes] == [
                    BankCandidateSource.PAYABLE_M12,
                    BankCandidateSource.RECEIVABLE_M13,
                ]
                assert len(await repository.conciliations(imported.statement.id)) == 2

    asyncio.run(scenario())


def test_partial_fuzzy_match_preserves_unmatched_movement_with_explanation() -> None:
    async def scenario() -> None:
        async with bank_statement_fixture() as data:
            content = _csv(
                "27/10/2026;-100,00;Pagamento conhecido;PAY-1;KNOWN",
                "28/10/2026;-75,00;Pagamento sem titulo;PAY-2;UNKNOWN",
            )
            async with data.database.session() as session, session.begin():
                repository = BankStatementRepository(session, company_id=data.company_id)
                imported = await BankStatementIngestionService(
                    BankStatementParserRegistry(),
                    repository,
                    clock=lambda: datetime(2026, 10, 28, 14, tzinfo=UTC),
                ).ingest(
                    _command(
                        company_id=data.company_id,
                        bank_account_id=uuid4(),
                        actor_id=data.actor_id,
                        content=content,
                    )
                )
                known = imported.statement.movements[0]
                provider = StaticCandidateProvider(
                    {
                        known.external_id: (
                            _candidate(
                                known,
                                source=BankCandidateSource.TREASURY_M12,
                                expected_on=date(2026, 10, 28),
                            ),
                        )
                    }
                )
                result = await BankConciliationService(repository, provider).reconcile(
                    imported.statement.id,
                    actor_id=data.actor_id,
                    occurred_at=datetime(2026, 10, 28, 14, 5, tzinfo=UTC),
                )

                assert result.statement.status is BankStatementStatus.PARTIALLY_RECONCILED
                assert [value.classification for value in result.outcomes] == [
                    BankConciliationClassification.RECONCILED,
                    BankConciliationClassification.PENDING,
                ]
                assert result.outcomes[1].reason is ReconciliationReason.NO_CANDIDATE

    asyncio.run(scenario())


def test_equal_candidates_are_ambiguous_and_do_not_mutate_the_statement() -> None:
    async def scenario() -> None:
        async with bank_statement_fixture() as data:
            content = _csv("28/10/2026;-100,00;Pagamento duplicado;PAY-AMB;AMB")
            async with data.database.session() as session, session.begin():
                repository = BankStatementRepository(session, company_id=data.company_id)
                imported = await BankStatementIngestionService(
                    BankStatementParserRegistry(), repository
                ).ingest(
                    _command(
                        company_id=data.company_id,
                        bank_account_id=uuid4(),
                        actor_id=data.actor_id,
                        content=content,
                    )
                )
                movement = imported.statement.movements[0]
                provider = StaticCandidateProvider(
                    {
                        movement.external_id: (
                            _candidate(movement, source=BankCandidateSource.PAYABLE_M12),
                            _candidate(movement, source=BankCandidateSource.PAYABLE_M12),
                        )
                    }
                )
                result = await BankConciliationService(repository, provider).reconcile(
                    imported.statement.id,
                    actor_id=data.actor_id,
                    occurred_at=datetime(2026, 10, 28, 15, tzinfo=UTC),
                )

                assert result.statement == imported.statement
                assert result.outcomes[0].classification is BankConciliationClassification.AMBIGUOUS
                assert result.outcomes[0].reason is ReconciliationReason.AMBIGUOUS_CANDIDATES
                assert result.outcomes[0].candidate_count == 2
                assert await repository.conciliations(imported.statement.id) == ()

    asyncio.run(scenario())


def test_bank_fees_interest_and_iof_are_explainable_direct_entries() -> None:
    async def scenario() -> None:
        async with bank_statement_fixture() as data:
            content = _csv(
                "26/10/2026;-12,00;Tarifa bancaria;;FEE",
                "27/10/2026;3,50;Juros rendimento;;INTEREST",
                "28/10/2026;-1,25;IOF operacao;;IOF",
            )
            async with data.database.session() as session, session.begin():
                repository = BankStatementRepository(session, company_id=data.company_id)
                imported = await BankStatementIngestionService(
                    BankStatementParserRegistry(), repository
                ).ingest(
                    _command(
                        company_id=data.company_id,
                        bank_account_id=uuid4(),
                        actor_id=data.actor_id,
                        content=content,
                    )
                )
                provider = StaticCandidateProvider({})
                result = await BankConciliationService(repository, provider).reconcile(
                    imported.statement.id,
                    actor_id=data.actor_id,
                    occurred_at=datetime(2026, 10, 28, 16, tzinfo=UTC),
                )

                assert [value.kind for value in result.statement.movements] == [
                    BankTransactionKind.BANK_FEE,
                    BankTransactionKind.INTEREST,
                    BankTransactionKind.TAX,
                ]
                assert [value.classification for value in result.outcomes] == [
                    BankConciliationClassification.DIRECT_BANK_FEE,
                    BankConciliationClassification.DIRECT_INTEREST,
                    BankConciliationClassification.DIRECT_TAX,
                ]
                assert provider.calls == []
                assert result.statement.version == 1

    asyncio.run(scenario())


def test_payable_candidate_adapter_reads_only_paid_m12_installments_in_tenant() -> None:
    async def scenario() -> None:
        async with bank_statement_fixture() as data:
            payable_id = uuid4()
            installment_id = uuid4()
            actor_id = data.actor_id
            async with data.database.session() as session, session.begin():
                session.add(
                    PayableModel(
                        id=payable_id,
                        company_id=data.company_id,
                        document_number="PAY-REAL-182",
                        supplier_id=uuid4(),
                        supplier_tax_id="12345678000195",
                        provisional_entry_id=None,
                        currency="BRL",
                        nominal_amount=Decimal("100.00"),
                        interest_amount=Decimal("0.00"),
                        discount_amount=Decimal("0.00"),
                        surcharge_amount=Decimal("0.00"),
                        status="PAID",
                        decision_by=uuid4(),
                        decision_reason="Approved",
                        version=1,
                        created_by=actor_id,
                        updated_by=actor_id,
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
                        amount=Decimal("100.00"),
                        status="PAID",
                        schedule_id=uuid4(),
                        paid_on=date(2026, 10, 28),
                        payment_reference="PAY-REAL-182",
                        created_by=actor_id,
                        updated_by=actor_id,
                    )
                )
                await session.flush()
                movement = BankMovement(
                    id=uuid4(),
                    company_id=data.company_id,
                    bank_account_id=uuid4(),
                    external_id="REAL-M12",
                    booked_on=date(2026, 10, 28),
                    amount=Decimal("100.00"),
                    direction=BankMovementDirection.DEBIT,
                    kind=BankTransactionKind.PAYMENT,
                    description="Pagamento real M12",
                    document_number="PAY-REAL-182",
                )
                candidates = await PayableBankCandidateProvider(
                    session, company_id=data.company_id
                ).candidates_for(movement)

                assert len(candidates) == 1
                assert candidates[0].candidate.reference_id == installment_id
                assert candidates[0].source is BankCandidateSource.PAYABLE_M12

    asyncio.run(scenario())
