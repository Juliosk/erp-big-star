"""Cash Flow composition integration across reconciliation, M12 and snapshots."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import (
    CashFlowCompositionService,
    ComposeCashFlowProjection,
    ReceivableCashFlowFeed,
    UnavailableReceivableProvider,
)
from erp.modules.finance.domain import (
    BankMovement,
    BankMovementDirection,
    BankStatement,
    BankStatementSource,
    BankTransactionKind,
    BusinessCalendar,
    BusinessDayConvention,
    CashAmount,
    CashFlowCategory,
    CashFlowCertainty,
    CashFlowDateHorizon,
    CashFlowDirection,
    CashFlowEngine,
    CashFlowItem,
    CashFlowMissingSource,
    CashFlowOrigin,
    CashFlowScenario,
    LiquidityState,
    PaymentBatch,
    PaymentBatchStatus,
    ProjectionGranularity,
    TreasurySegregationPolicy,
)
from erp.modules.finance.infrastructure import (
    BankStatementModel,
    BankStatementRepository,
    CashFlowAuditLogModel,
    CashFlowProjectionRepository,
    CashFlowProjectionSnapshotModel,
    CashFlowScenarioDefinitionModel,
    PaymentBatchRepository,
    PostgresBankPositionProvider,
    PostgresPayableCommitmentProvider,
)
from tests.integration.test_treasury_repository import TreasuryFixture, treasury_fixture

pytestmark = pytest.mark.integration


@asynccontextmanager
async def composition_fixture() -> AsyncIterator[TreasuryFixture]:
    async with treasury_fixture() as fixture:
        data = fixture.matching.data
        companies = (data.company_id, data.other_company_id)
        try:
            yield fixture
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(text("SET LOCAL erp.allow_cash_flow_cleanup = 'on'"))
                await session.execute(
                    delete(CashFlowAuditLogModel).where(
                        CashFlowAuditLogModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(CashFlowProjectionSnapshotModel).where(
                        CashFlowProjectionSnapshotModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    delete(CashFlowScenarioDefinitionModel).where(
                        CashFlowScenarioDefinitionModel.company_id.in_(companies)
                    )
                )
                await session.execute(
                    text("SET LOCAL erp.allow_bank_reconciliation_audit_cleanup = 'on'")
                )
                await session.execute(
                    delete(BankStatementModel).where(BankStatementModel.company_id.in_(companies))
                )


def _bank_statement(
    *,
    company_id: UUID,
    account_id: UUID | None = None,
    statement_id: UUID | None = None,
    period_end: date = date(2026, 11, 30),
    imported_at: datetime = datetime(2026, 11, 30, 20, tzinfo=UTC),
    opening_balance: Decimal = Decimal("900.00"),
    credit: Decimal = Decimal("100.00"),
) -> BankStatement:
    bank_account_id = account_id or uuid4()
    return BankStatement(
        id=statement_id or uuid4(),
        company_id=company_id,
        bank_account_id=bank_account_id,
        bank_code="001",
        account_reference="AG 1234 / CC 98765-0",
        period_start=date(2026, 11, 1),
        period_end=period_end,
        imported_at=imported_at,
        source=BankStatementSource.OFX,
        source_hash=uuid4().hex * 2,
        movements=(
            BankMovement(
                id=uuid4(),
                company_id=company_id,
                bank_account_id=bank_account_id,
                external_id=f"CASH-{uuid4().hex}",
                booked_on=period_end,
                amount=credit,
                direction=BankMovementDirection.CREDIT,
                kind=BankTransactionKind.RECEIPT,
                description="Saldo bancario realizado",
                document_number="CASH-190",
            ),
        ),
        opening_balance=opening_balance,
        closing_balance=opening_balance + credit,
    )


def _command(
    *,
    company_id: UUID,
    projection_id: UUID | None = None,
    scenario_id: UUID | None = None,
    calculated_at: datetime = datetime(2026, 12, 1, 8, tzinfo=UTC),
    predicted_items: tuple[CashFlowItem, ...] = (),
) -> ComposeCashFlowProjection:
    horizon = CashFlowDateHorizon(date(2026, 12, 1), date(2026, 12, 31))
    return ComposeCashFlowProjection(
        projection_id=projection_id or uuid4(),
        company_id=company_id,
        as_of=horizon.start_on,
        calculated_at=calculated_at,
        horizon=horizon,
        granularity=ProjectionGranularity.DAILY,
        minimum_reserve=CashAmount(Decimal("300.00")),
        scenario=CashFlowScenario(
            id=scenario_id or uuid4(),
            name="Base realizado e comprometido",
            business_day_convention=BusinessDayConvention.UNADJUSTED,
        ),
        predicted_items=predicted_items,
    )


def _predicted(company_id: UUID) -> CashFlowItem:
    return CashFlowItem(
        company_id=company_id,
        amount=CashAmount(Decimal("50.00")),
        occurs_on=date(2026, 12, 15),
        direction=CashFlowDirection.OUTFLOW,
        category=CashFlowCategory.OPERATING,
        certainty=CashFlowCertainty.SCENARIO,
        origin=CashFlowOrigin.MANUAL_SCENARIO,
        reference_id=None,
    )


async def _approved_batch(
    session: AsyncSession,
    fixture: TreasuryFixture,
    *,
    batch: PaymentBatch | None = None,
) -> PaymentBatch:
    data = fixture.matching.data
    repository = PaymentBatchRepository(session, company_id=data.company_id)
    source = batch or fixture.batch
    await repository.add(source, actor_id=fixture.batch_creator)
    pending = source.submit_for_approval()
    await repository.save(pending, actor_id=fixture.batch_creator)
    approved = pending.approve(
        actor_id=fixture.batch_approver,
        policy=TreasurySegregationPolicy(),
    )
    await repository.save(approved, actor_id=fixture.batch_approver)
    assert approved.status is PaymentBatchStatus.APPROVED
    return approved


def test_composes_realized_committed_predicted_and_persists_versions() -> None:
    async def scenario() -> None:
        async with composition_fixture() as fixture:
            data = fixture.matching.data
            account_id = uuid4()
            statement = _bank_statement(company_id=data.company_id, account_id=account_id)
            older_statement = _bank_statement(
                company_id=data.company_id,
                account_id=account_id,
                period_end=date(2026, 11, 15),
                imported_at=datetime(2026, 11, 15, 20, tzinfo=UTC),
                opening_balance=Decimal("700.00"),
            )
            second_account = _bank_statement(
                company_id=data.company_id,
                opening_balance=Decimal("400.00"),
            )
            hindsight_statement = _bank_statement(
                company_id=data.company_id,
                imported_at=datetime(2026, 12, 2, 8, tzinfo=UTC),
                opening_balance=Decimal("9900.00"),
            )
            projection_id = uuid4()
            scenario_id = uuid4()
            command = _command(
                company_id=data.company_id,
                projection_id=projection_id,
                scenario_id=scenario_id,
                predicted_items=(_predicted(data.company_id),),
            )
            async with data.database.session() as session, session.begin():
                statements = BankStatementRepository(session, company_id=data.company_id)
                for imported in (
                    older_statement,
                    statement,
                    second_account,
                    hindsight_statement,
                ):
                    await statements.add(
                        imported,
                        actor_id=data.actor_id,
                        original_file_name="cash-flow.ofx",
                        file_size_bytes=512,
                    )
                await _approved_batch(session, fixture)
                projections = CashFlowProjectionRepository(session, company_id=data.company_id)
                service = CashFlowCompositionService(
                    engine=CashFlowEngine(BusinessCalendar()),
                    bank_positions=PostgresBankPositionProvider(session),
                    payables=PostgresPayableCommitmentProvider(session),
                    receivables=UnavailableReceivableProvider(),
                    projections=projections,
                )
                assert (
                    await PostgresBankPositionProvider(session).positions(
                        company_id=data.company_id,
                        as_of=command.as_of,
                        currency="USD",
                    )
                    == ()
                )
                first = await service.compose(command, actor_id=data.actor_id)
                assert first.projection.version == 1
                assert first.projection.opening_balance.amount == Decimal("1500.00")
                assert len(first.bank_positions) == 2
                assert {position.balance.amount for position in first.bank_positions} == {
                    Decimal("500.00"),
                    Decimal("1000.00"),
                }
                assert len(first.committed_items) == 1
                assert first.committed_items[0].occurs_on == fixture.batch.scheduled_date
                assert first.projection.summary.committed_outflows.amount == Decimal("125.40")
                assert first.projection.summary.scenario_outflows.amount == Decimal("50.00")
                assert first.projection.summary.operational_closing_balance.amount == Decimal("1374.60")
                assert first.projection.summary.scenario_closing_balance.amount == Decimal("1324.60")
                assert first.projection.liquidity_state is LiquidityState.INCOMPLETE
                assert [gap.source for gap in first.source_gaps] == [
                    CashFlowMissingSource.RECEIVABLES
                ]

                second = await service.compose(
                    replace(
                        command,
                        calculated_at=datetime(2026, 12, 1, 9, tzinfo=UTC),
                    ),
                    actor_id=data.actor_id,
                )
                assert second.projection.version == 2
                assert [value.version for value in await projections.versions(projection_id)] == [1, 2]
                assert [entry.action for entry in await projections.audit_log(projection_id)] == [
                    "CREATED",
                    "RECALCULATED",
                ]

    asyncio.run(scenario())


def test_missing_authorities_are_explicit_and_cross_tenant_sources_do_not_leak() -> None:
    async def scenario() -> None:
        async with composition_fixture() as fixture:
            data = fixture.matching.data
            async with data.database.session() as session, session.begin():
                service = CashFlowCompositionService(
                    engine=CashFlowEngine(BusinessCalendar()),
                    bank_positions=PostgresBankPositionProvider(session),
                    payables=PostgresPayableCommitmentProvider(session),
                    receivables=UnavailableReceivableProvider("M13 remains outside the current slice."),
                    projections=CashFlowProjectionRepository(
                        session, company_id=data.other_company_id
                    ),
                )
                result = await service.compose(
                    _command(company_id=data.other_company_id),
                    actor_id=data.actor_id,
                )
                assert result.projection.opening_balance.amount == Decimal("0.00")
                assert result.committed_items == ()
                assert [gap.source for gap in result.source_gaps] == [
                    CashFlowMissingSource.BANK_POSITION,
                    CashFlowMissingSource.RECEIVABLES,
                ]
                assert result.source_gaps[1].reason == "M13 remains outside the current slice."

    asyncio.run(scenario())


def test_composition_uses_the_callers_transaction_boundary() -> None:
    async def scenario() -> None:
        async with composition_fixture() as fixture:
            data = fixture.matching.data
            projection_id = uuid4()

            async def compose_then_fail() -> None:
                async with data.database.session() as session, session.begin():
                    service = CashFlowCompositionService(
                        engine=CashFlowEngine(BusinessCalendar()),
                        bank_positions=PostgresBankPositionProvider(session),
                        payables=PostgresPayableCommitmentProvider(session),
                        receivables=UnavailableReceivableProvider(),
                        projections=CashFlowProjectionRepository(
                            session, company_id=data.company_id
                        ),
                    )
                    await service.compose(
                        _command(company_id=data.company_id, projection_id=projection_id),
                        actor_id=data.actor_id,
                    )
                    raise RuntimeError("force rollback")

            with pytest.raises(RuntimeError, match="force rollback"):
                await compose_then_fail()

            async with data.database.session() as session:
                assert (
                    await CashFlowProjectionRepository(
                        session, company_id=data.company_id
                    ).get(projection_id)
                    is None
                )

    asyncio.run(scenario())


def test_overdue_approved_batch_is_due_on_projection_start() -> None:
    async def scenario() -> None:
        async with composition_fixture() as fixture:
            data = fixture.matching.data
            overdue_batch = replace(fixture.batch, scheduled_date=date(2026, 11, 30))
            horizon = CashFlowDateHorizon(date(2026, 12, 1), date(2026, 12, 31))
            async with data.database.session() as session, session.begin():
                await _approved_batch(session, fixture, batch=overdue_batch)
                commitments = await PostgresPayableCommitmentProvider(session).commitments(
                    company_id=data.company_id,
                    horizon=horizon,
                    currency="BRL",
                )
                assert len(commitments) == 1
                assert commitments[0].occurs_on == horizon.start_on

    asyncio.run(scenario())


class AvailableReceivableProvider:
    def __init__(self, item: CashFlowItem) -> None:
        self._item = item

    async def receivables(
        self,
        *,
        company_id: UUID,
        horizon: CashFlowDateHorizon,
        currency: str,
    ) -> ReceivableCashFlowFeed:
        assert self._item.company_id == company_id
        assert horizon.contains(self._item.occurs_on)
        assert self._item.amount.currency == currency
        return ReceivableCashFlowFeed(items=(self._item,), available=True)


def test_available_m13_contract_removes_receivable_gap_without_speculation() -> None:
    async def scenario() -> None:
        async with composition_fixture() as fixture:
            data = fixture.matching.data
            statement = _bank_statement(company_id=data.company_id)
            receivable = CashFlowItem(
                company_id=data.company_id,
                amount=CashAmount(Decimal("200.00")),
                occurs_on=date(2026, 12, 20),
                direction=CashFlowDirection.INFLOW,
                category=CashFlowCategory.OPERATING,
                certainty=CashFlowCertainty.COMMITTED,
                origin=CashFlowOrigin.RECEIVABLE_INSTALLMENT,
                reference_id=uuid4(),
            )
            async with data.database.session() as session, session.begin():
                await BankStatementRepository(session, company_id=data.company_id).add(
                    statement,
                    actor_id=data.actor_id,
                    original_file_name="cash-flow-m13.ofx",
                    file_size_bytes=512,
                )
                result = await CashFlowCompositionService(
                    engine=CashFlowEngine(BusinessCalendar()),
                    bank_positions=PostgresBankPositionProvider(session),
                    payables=PostgresPayableCommitmentProvider(session),
                    receivables=AvailableReceivableProvider(receivable),
                    projections=CashFlowProjectionRepository(
                        session, company_id=data.company_id
                    ),
                ).compose(_command(company_id=data.company_id), actor_id=data.actor_id)
                assert result.source_gaps == ()
                assert result.receivable_items == (receivable,)
                assert result.projection.summary.committed_inflows.amount == Decimal("200.00")
                assert result.projection.liquidity_state is LiquidityState.HEALTHY

    asyncio.run(scenario())
