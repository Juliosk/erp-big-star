"""Cash Flow snapshot persistence integration against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect, text, update
from sqlalchemy.exc import DBAPIError

from erp.modules.finance.domain import (
    BusinessCalendar,
    BusinessDayConvention,
    CashAmount,
    CashFlowCategory,
    CashFlowCertainty,
    CashFlowConflictError,
    CashFlowDateHorizon,
    CashFlowDirection,
    CashFlowEngine,
    CashFlowItem,
    CashFlowOrigin,
    CashFlowProjection,
    CashFlowProjectionInput,
    CashFlowScenario,
    CashFlowScopeError,
    FinanceVersionConflictError,
    ProjectionGranularity,
)
from erp.modules.finance.infrastructure import (
    CashFlowAuditLogModel,
    CashFlowProjectionRepository,
    CashFlowProjectionSnapshotModel,
    CashFlowScenarioDefinitionModel,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_payable_repository import finance_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


@asynccontextmanager
async def cash_flow_fixture() -> AsyncIterator[ProcurementFixture]:
    async with finance_fixture() as data:
        companies = (data.company_id, data.other_company_id)
        try:
            yield data
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


def _projection(
    data: ProcurementFixture,
    *,
    company_id: UUID | None = None,
    projection_id: UUID | None = None,
    scenario_id: UUID | None = None,
    scenario_name: str = "Base 30 dias",
    version: int = 1,
    calculated_at: datetime = datetime(2026, 10, 31, 12, tzinfo=UTC),
) -> CashFlowProjection:
    tenant = company_id or data.company_id
    horizon = CashFlowDateHorizon(date(2026, 10, 31), date(2026, 11, 6))
    scenario = CashFlowScenario(
        id=scenario_id or uuid4(),
        name=scenario_name,
        receivable_delay_days=2,
        cost_variation_rate=Decimal("0.0500"),
        business_day_convention=BusinessDayConvention.FOLLOWING,
    )
    items = (
        CashFlowItem(
            company_id=tenant,
            amount=CashAmount(Decimal("250.00")),
            occurs_on=date(2026, 10, 31),
            direction=CashFlowDirection.INFLOW,
            category=CashFlowCategory.OPERATING,
            certainty=CashFlowCertainty.REALIZED,
            origin=CashFlowOrigin.BANK_RECONCILIATION,
            reference_id=uuid4(),
        ),
        CashFlowItem(
            company_id=tenant,
            amount=CashAmount(Decimal("100.00")),
            occurs_on=date(2026, 11, 2),
            direction=CashFlowDirection.OUTFLOW,
            category=CashFlowCategory.OPERATING,
            certainty=CashFlowCertainty.COMMITTED,
            origin=CashFlowOrigin.PAYABLE_INSTALLMENT,
            reference_id=uuid4(),
        ),
    )
    request = CashFlowProjectionInput(
        projection_id=projection_id or uuid4(),
        company_id=tenant,
        as_of=horizon.start_on,
        calculated_at=calculated_at,
        horizon=horizon,
        granularity=ProjectionGranularity.DAILY,
        opening_balance=CashAmount(Decimal("1000.00")),
        minimum_reserve=CashAmount(Decimal("200.00")),
        scenario=scenario,
        items=items,
        version=version,
    )
    return CashFlowEngine(BusinessCalendar()).project(request)


def test_round_trip_versions_scenario_reuse_and_append_only_evidence() -> None:
    async def scenario() -> None:
        async with cash_flow_fixture() as data:
            scenario_id = uuid4()
            projection = _projection(data, scenario_id=scenario_id)
            async with data.database.session() as session, session.begin():
                repository = CashFlowProjectionRepository(session, company_id=data.company_id)
                await repository.add(projection, actor_id=data.actor_id)
                assert await repository.get(projection.id) == projection
                assert await repository.get(projection.id, version=1) == projection

                recalculated = replace(
                    projection,
                    calculated_at=projection.calculated_at + timedelta(minutes=5),
                    version=2,
                )
                await repository.save(
                    recalculated,
                    actor_id=data.actor_id,
                    expected_version=1,
                )
                assert await repository.get(projection.id) == recalculated
                assert await repository.versions(projection.id) == (projection, recalculated)
                audit = await repository.audit_log(projection.id)
                assert [entry.action for entry in audit] == ["CREATED", "RECALCULATED"]
                assert audit[1].details["bucket_count"] == 7

                second = _projection(
                    data,
                    scenario_id=scenario_id,
                    projection_id=uuid4(),
                )
                await repository.add(second, actor_id=data.actor_id)
                assert await repository.get(second.id) == second

                savepoint = await session.begin_nested()
                with pytest.raises(DBAPIError, match="append-only"):
                    await session.execute(
                        update(CashFlowProjectionSnapshotModel)
                        .where(CashFlowProjectionSnapshotModel.id == projection.id)
                        .values(liquidity_state="CRITICAL")
                    )
                await savepoint.rollback()

                savepoint = await session.begin_nested()
                with pytest.raises(DBAPIError, match="append-only"):
                    await session.execute(
                        update(CashFlowAuditLogModel)
                        .where(CashFlowAuditLogModel.id == audit[0].id)
                        .values(details={"tampered": True})
                    )
                await savepoint.rollback()

                savepoint = await session.begin_nested()
                with pytest.raises(DBAPIError, match="append-only"):
                    await session.execute(
                        update(CashFlowScenarioDefinitionModel)
                        .where(CashFlowScenarioDefinitionModel.id == scenario_id)
                        .values(name="Alterado")
                    )
                await savepoint.rollback()

    asyncio.run(scenario())


def test_tenant_isolation_transaction_rollback_and_conflicts() -> None:
    async def scenario() -> None:
        async with cash_flow_fixture() as data:
            own = _projection(data)
            foreign = _projection(data, company_id=data.other_company_id)
            async with data.database.session() as session, session.begin():
                own_repository = CashFlowProjectionRepository(
                    session, company_id=data.company_id
                )
                foreign_repository = CashFlowProjectionRepository(
                    session, company_id=data.other_company_id
                )

                nested = await session.begin_nested()
                transient = _projection(data)
                await own_repository.add(transient, actor_id=data.actor_id)
                await nested.rollback()
                assert await own_repository.get(transient.id) is None

                await own_repository.add(own, actor_id=data.actor_id)
                assert await foreign_repository.get(own.id) is None
                with pytest.raises(CashFlowScopeError):
                    await foreign_repository.add(own, actor_id=data.actor_id)
                await foreign_repository.add(foreign, actor_id=data.actor_id)
                assert await foreign_repository.get(foreign.id) == foreign

                duplicate = _projection(
                    data,
                    projection_id=own.id,
                    scenario_id=own.scenario.id,
                )
                savepoint = await session.begin_nested()
                with pytest.raises(CashFlowConflictError):
                    await own_repository.add(duplicate, actor_id=data.actor_id)
                await savepoint.rollback()

                conflicting_scenario = _projection(
                    data,
                    scenario_id=own.scenario.id,
                    scenario_name="Definição diferente",
                )
                with pytest.raises(CashFlowConflictError, match="another definition"):
                    await own_repository.add(conflicting_scenario, actor_id=data.actor_id)

    asyncio.run(scenario())


def test_optimistic_concurrency_and_repository_contracts() -> None:
    async def scenario() -> None:
        async with cash_flow_fixture() as data:
            projection = _projection(data)
            async with data.database.session() as session, session.begin():
                with pytest.raises(ValueError, match="company UUID"):
                    CashFlowProjectionRepository(session, company_id=UUID(int=0))
                repository = CashFlowProjectionRepository(session, company_id=data.company_id)
                with pytest.raises(TypeError, match="CashFlowProjection"):
                    await repository.add(object(), actor_id=data.actor_id)  # type: ignore[arg-type]
                with pytest.raises(ValueError, match="actor_id"):
                    await repository.add(projection, actor_id=UUID(int=0))
                with pytest.raises(ValueError, match="version one"):
                    await repository.add(replace(projection, version=2), actor_id=data.actor_id)

                await repository.add(projection, actor_id=data.actor_id)
                version_two = replace(projection, version=2)
                with pytest.raises(ValueError, match="expected_version"):
                    await repository.save(
                        version_two,
                        actor_id=data.actor_id,
                        expected_version=0,
                    )
                with pytest.raises(ValueError, match="one aggregate version"):
                    await repository.save(
                        replace(projection, version=3),
                        actor_id=data.actor_id,
                        expected_version=1,
                    )
                await repository.save(
                    version_two,
                    actor_id=data.actor_id,
                    expected_version=1,
                )
                with pytest.raises(FinanceVersionConflictError):
                    await repository.save(
                        version_two,
                        actor_id=data.actor_id,
                        expected_version=1,
                    )
                with pytest.raises(ValueError, match="projection_id"):
                    await repository.get(UUID(int=0))
                with pytest.raises(ValueError, match="version"):
                    await repository.get(projection.id, version=0)
                assert await repository.get(uuid4()) is None
                assert await repository.versions(uuid4()) == ()
                assert await repository.audit_log(uuid4()) == ()

    asyncio.run(scenario())


def test_migration_0048_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="finance"))
                    cash_flow_tables = {
                        "cash_flow_projection_snapshot",
                        "cash_flow_scenario_definition",
                        "cash_flow_audit_log",
                    }
                    assert cash_flow_tables.issubset(tables) is expected
                    if not expected:
                        return
                    primary_key = inspector.get_pk_constraint(
                        "cash_flow_projection_snapshot", schema="finance"
                    )
                    assert primary_key["constrained_columns"] == ["id", "version"]
                    foreign_keys = inspector.get_foreign_keys(
                        "cash_flow_audit_log", schema="finance"
                    )
                    assert any(
                        value["constrained_columns"]
                        == ["company_id", "projection_id", "projection_version"]
                        for value in foreign_keys
                    )
                    indexes = {
                        value["name"]
                        for value in inspector.get_indexes(
                            "cash_flow_projection_snapshot", schema="finance"
                        )
                    }
                    assert "ix_cash_flow_snapshot_company_as_of_horizon" in indexes
                    assert "ix_cash_flow_snapshot_company_calculated" in indexes

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0047")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0048")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")


__all__: list[str] = []
