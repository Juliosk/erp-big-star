"""Atomic M6 three-way matching execution, audit and Outbox integration."""

import asyncio
from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select

from erp.modules.procurement.application import (
    MATCHING_DISCREPANCY_DETECTED,
    MATCHING_SESSION_COMPLETED,
    ExecuteThreeWayMatch,
    MatchingExecutionEvent,
    ProcurementCommandMetadata,
    ThreeWayMatchingService,
)
from erp.modules.procurement.domain import ThreeWayMatchSessionStatus
from erp.modules.procurement.infrastructure import (
    MatchingAuditLogModel,
    MatchingSessionItemModel,
    PostgresMatchingEventPublisher,
    ThreeWayMatchRepository,
)
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_matching_repository import matching_fixture

pytestmark = pytest.mark.integration


def test_execution_persists_explainable_results_audit_and_outbox_atomically() -> None:
    async def scenario() -> None:
        async with matching_fixture() as fixture:
            data = fixture.data
            line = replace(
                fixture.aggregate.lines[0],
                invoiced_unit_price=fixture.aggregate.lines[0].invoiced_unit_price + 1,
            )
            pending = replace(fixture.aggregate, lines=(line,))
            metadata = ProcurementCommandMetadata.new()
            async with data.database.session() as session, session.begin():
                repository = ThreeWayMatchRepository(session, company_id=data.company_id)
                await repository.add(pending, actor_id=data.actor_id)
                result = await ThreeWayMatchingService(
                    repository, PostgresMatchingEventPublisher(session)
                ).execute(
                    ExecuteThreeWayMatch(
                        company_id=data.company_id,
                        matching_session_id=pending.id,
                        expected_version=1,
                        actor_id=data.actor_id,
                        metadata=metadata,
                        occurred_at=pending.created_at,
                    )
                )

                assert result.session.status is ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED
                assert len(result.event_ids) == 2
                item = await session.scalar(
                    select(MatchingSessionItemModel).where(
                        MatchingSessionItemModel.company_id == data.company_id,
                        MatchingSessionItemModel.matching_session_id == pending.id,
                    )
                )
                assert item is not None
                assert item.result_status == "PRICE_MISMATCH"
                assert item.reasons == ["UNIT_PRICE_TOLERANCE_EXCEEDED"]

                audit = tuple(
                    await session.scalars(
                        select(MatchingAuditLogModel)
                        .where(
                            MatchingAuditLogModel.company_id == data.company_id,
                            MatchingAuditLogModel.matching_session_id == pending.id,
                        )
                        .order_by(MatchingAuditLogModel.aggregate_version)
                    )
                )
                assert [entry.to_status for entry in audit] == [
                    "PENDING",
                    "RUNNING",
                    "DISCREPANCY_DETECTED",
                ]
                assert result.session.report is not None
                line_result = result.session.report.lines[0]
                assert audit[-1].details["line_results"][0] == {
                    "match_key": "LINE-001",
                    "status": "PRICE_MISMATCH",
                    "quantity_delta": str(line_result.quantity_delta),
                    "unit_price_delta": str(line_result.unit_price_delta),
                    "allowed_quantity_delta": str(line_result.allowed_quantity_delta),
                    "allowed_unit_price_delta": str(line_result.allowed_unit_price_delta),
                    "reasons": ["UNIT_PRICE_TOLERANCE_EXCEEDED"],
                }

                outbox = tuple(
                    await session.scalars(
                        select(OutboxEventModel)
                        .where(
                            OutboxEventModel.aggregate_id == pending.id,
                            OutboxEventModel.source_module == "procurement",
                        )
                        .order_by(OutboxEventModel.occurred_at, OutboxEventModel.event_type)
                    )
                )
                assert {event.event_type for event in outbox} == {
                    MATCHING_SESSION_COMPLETED,
                    MATCHING_DISCREPANCY_DETECTED,
                }
                assert {event.event_id for event in outbox} == set(result.event_ids)
                assert all(event.request_id == metadata.request_id for event in outbox)
                discrepancy = next(
                    event
                    for event in outbox
                    if event.event_type == MATCHING_DISCREPANCY_DETECTED
                )
                assert discrepancy.payload["payload"]["discrepancy_count"] == 1
                assert discrepancy.payload["payload"]["discrepancies"][0]["match_key"] == (
                    "LINE-001"
                )

                await session.execute(
                    delete(OutboxEventModel).where(OutboxEventModel.aggregate_id == pending.id)
                )

    asyncio.run(scenario())


def test_outbox_failure_rolls_back_execution_and_audit_log() -> None:
    class FailAfterFirstEvent:
        def __init__(self, publisher: PostgresMatchingEventPublisher) -> None:
            self._publisher = publisher
            self._calls = 0

        async def publish(
            self,
            event: MatchingExecutionEvent,
            *,
            metadata: ProcurementCommandMetadata,
        ) -> UUID:
            self._calls += 1
            if self._calls == 2:
                raise RuntimeError("outbox unavailable")
            return await self._publisher.publish(event, metadata=metadata)

    async def scenario() -> None:
        async with matching_fixture() as fixture:
            data = fixture.data
            line = replace(
                fixture.aggregate.lines[0],
                received_quantity=fixture.aggregate.lines[0].received_quantity - 1,
            )
            pending = replace(fixture.aggregate, lines=(line,))
            async with data.database.session() as session, session.begin():
                await ThreeWayMatchRepository(session, company_id=data.company_id).add(
                    pending, actor_id=data.actor_id
                )

            async def execute_with_failed_outbox() -> None:
                async with data.database.session() as session, session.begin():
                    repository = ThreeWayMatchRepository(session, company_id=data.company_id)
                    await ThreeWayMatchingService(
                        repository,
                        FailAfterFirstEvent(PostgresMatchingEventPublisher(session)),
                    ).execute(
                        ExecuteThreeWayMatch(
                            company_id=data.company_id,
                            matching_session_id=pending.id,
                            expected_version=1,
                            actor_id=data.actor_id,
                            metadata=ProcurementCommandMetadata.new(),
                            occurred_at=pending.created_at,
                        )
                    )

            with pytest.raises(RuntimeError, match="outbox unavailable"):
                await execute_with_failed_outbox()

            async with data.database.session() as session:
                persisted = await ThreeWayMatchRepository(
                    session, company_id=data.company_id
                ).get(pending.id)
                assert persisted == pending
                audit_count = await session.scalar(
                    select(func.count())
                    .select_from(MatchingAuditLogModel)
                    .where(MatchingAuditLogModel.matching_session_id == pending.id)
                )
                outbox_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(OutboxEventModel.aggregate_id == pending.id)
                )
                assert audit_count == 1
                assert outbox_count == 0

    asyncio.run(scenario())
