"""Cash Flow alert persistence, Audit and Outbox integration on PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import DBAPIError

from erp.modules.finance.application import (
    CashFlowAlertMetadata,
    CashFlowAlertService,
)
from erp.modules.finance.domain import (
    BusinessCalendar,
    CashAmount,
    CashFlowAlertEngine,
    CashFlowAlertPolicy,
    CashFlowAlertSource,
    CashFlowAlertType,
    CashFlowCategory,
    CashFlowCertainty,
    CashFlowDateHorizon,
    CashFlowDirection,
    CashFlowEngine,
    CashFlowItem,
    CashFlowOrigin,
    CashFlowProjection,
    CashFlowProjectionInput,
    CashFlowScenario,
    ProjectionGranularity,
)
from erp.modules.finance.infrastructure import (
    CashFlowAlertModel,
    CashFlowProjectionRepository,
    PostgresCashFlowAlertRecorder,
)
from erp.platform.audit.models import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.outbox.models import OutboxEventModel
from tests.integration.test_cash_flow_repository import cash_flow_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


@asynccontextmanager
async def alert_fixture() -> AsyncIterator[ProcurementFixture]:
    async with cash_flow_fixture() as data:
        companies = (data.company_id, data.other_company_id)
        try:
            yield data
        finally:
            async with data.database.session() as session, session.begin():
                alert_ids = tuple(
                    await session.scalars(
                        select(CashFlowAlertModel.id).where(
                            CashFlowAlertModel.company_id.in_(companies)
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
                        CashFlowAlertModel.company_id.in_(companies)
                    )
                )


def _risk_projection(data: ProcurementFixture) -> CashFlowProjection:
    horizon = CashFlowDateHorizon(date(2026, 11, 4), date(2026, 11, 10))
    return CashFlowEngine(BusinessCalendar()).project(
        CashFlowProjectionInput(
            projection_id=uuid4(),
            company_id=data.company_id,
            as_of=horizon.start_on,
            calculated_at=datetime(2026, 11, 4, 12, tzinfo=UTC),
            horizon=horizon,
            granularity=ProjectionGranularity.DAILY,
            opening_balance=CashAmount(Decimal("100.00")),
            minimum_reserve=CashAmount(Decimal("50.00")),
            scenario=CashFlowScenario(id=uuid4(), name="Alerta integração"),
            items=(
                CashFlowItem(
                    company_id=data.company_id,
                    amount=CashAmount(Decimal("150.00")),
                    occurs_on=horizon.start_on,
                    direction=CashFlowDirection.OUTFLOW,
                    category=CashFlowCategory.OPERATING,
                    certainty=CashFlowCertainty.COMMITTED,
                    origin=CashFlowOrigin.PAYABLE_INSTALLMENT,
                    reference_id=uuid4(),
                ),
            ),
        )
    )


def _metadata(data: ProcurementFixture) -> CashFlowAlertMetadata:
    return CashFlowAlertMetadata(
        actor_id=data.actor_id,
        request_id=uuid4(),
        correlation_id=uuid4(),
        detected_at=datetime(2026, 11, 4, 12, 5, tzinfo=UTC),
    )


def test_alerts_audit_and_outbox_are_atomic_append_only_and_idempotent() -> None:
    async def scenario() -> None:
        async with alert_fixture() as data:
            projection = _risk_projection(data)
            async with data.database.session() as session, session.begin():
                await CashFlowProjectionRepository(
                    session, company_id=data.company_id
                ).add(projection, actor_id=data.actor_id)
                service = CashFlowAlertService(
                    CashFlowAlertEngine(CashFlowAlertPolicy()),
                    PostgresCashFlowAlertRecorder(session),
                )
                first = await service.evaluate_and_record(
                    projection,
                    source=CashFlowAlertSource.PROJECTION,
                    metadata=_metadata(data),
                )
                second = await service.evaluate_and_record(
                    projection,
                    source=CashFlowAlertSource.PROJECTION,
                    metadata=_metadata(data),
                )
                assert first
                assert second == ()
                alert_ids = tuple(item.alert.id for item in first)
                stored = tuple(
                    await session.scalars(
                        select(CashFlowAlertModel).where(
                            CashFlowAlertModel.id.in_(alert_ids)
                        )
                    )
                )
                assert len(stored) == len(first)
                assert {item.alert_type for item in stored} >= {
                    CashFlowAlertType.CASH_RUPTURE.value,
                    CashFlowAlertType.DATE_CONCENTRATION.value,
                }
                audits = tuple(
                    await session.scalars(
                        select(AuditEventModel).where(
                            AuditEventModel.entity_type == "cash_flow_alert",
                            AuditEventModel.entity_id.in_(alert_ids),
                        )
                    )
                )
                events = tuple(
                    await session.scalars(
                        select(OutboxEventModel).where(
                            OutboxEventModel.aggregate_type == "cash_flow_alert",
                            OutboxEventModel.aggregate_id.in_(alert_ids),
                        )
                    )
                )
                assert len(audits) == len(first)
                assert len(events) == len(first)
                assert {event.event_id for event in events} == {
                    item.event_id for item in first
                }

                nested = await session.begin_nested()
                transient = await service.evaluate_and_record(
                    projection,
                    source=CashFlowAlertSource.SCENARIO,
                    metadata=_metadata(data),
                )
                transient_ids = tuple(item.alert.id for item in transient)
                await nested.rollback()
                assert (
                    await session.scalar(
                        select(CashFlowAlertModel.id).where(
                            CashFlowAlertModel.id.in_(transient_ids)
                        )
                    )
                    is None
                )

                nested = await session.begin_nested()
                with pytest.raises(DBAPIError, match="append-only"):
                    await session.execute(
                        update(CashFlowAlertModel)
                        .where(CashFlowAlertModel.id == alert_ids[0])
                        .values(severity="WARNING")
                    )
                await nested.rollback()

    asyncio.run(scenario())


def test_migration_0050_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:
                tables = await connection.run_sync(
                    lambda sync: inspect(sync).get_table_names(schema="finance")
                )
                assert ("cash_flow_alert" in tables) is expected
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0049")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0050")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")


__all__: list[str] = []
