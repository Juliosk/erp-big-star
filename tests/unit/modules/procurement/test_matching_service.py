"""Application tests for deterministic and explainable three-way matching."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.procurement.application import (
    MATCHING_DISCREPANCY_DETECTED,
    MATCHING_SESSION_COMPLETED,
    ExecuteThreeWayMatch,
    MatchingExecutionEvent,
    ProcurementCommandMetadata,
    ThreeWayMatchingService,
    matching_execution_events,
)
from erp.modules.procurement.domain import (
    FinancialMatchSnapshot,
    MatchingTolerancePolicy,
    MatchingVersionConflictError,
    MatchStatus,
    PurchaseOrderMatchSnapshot,
    ReceivingFiscalMatchSnapshot,
    ThreeWayMatchLine,
    ThreeWayMatchSession,
    VersionedArtifactReference,
)
from erp.platform.errors import ApplicationError

OCCURRED_AT = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)


class FakeMatchingRepository:
    def __init__(self, aggregate: ThreeWayMatchSession | None) -> None:
        self.aggregate = aggregate
        self.saves: list[ThreeWayMatchSession] = []
        self.fail_with: ValueError | None = None

    async def get(self, matching_session_id: UUID) -> ThreeWayMatchSession | None:
        if self.aggregate is None or self.aggregate.id != matching_session_id:
            return None
        return self.aggregate

    async def save(
        self,
        aggregate: ThreeWayMatchSession,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> ThreeWayMatchSession:
        assert actor_id == aggregate.created_by
        assert self.aggregate is not None
        assert expected_version == self.aggregate.version
        if self.fail_with is not None:
            raise self.fail_with
        self.aggregate = aggregate
        self.saves.append(aggregate)
        return aggregate


class CollectingMatchingEvents:
    def __init__(self) -> None:
        self.events: list[MatchingExecutionEvent] = []

    async def publish(
        self,
        event: MatchingExecutionEvent,
        *,
        metadata: ProcurementCommandMetadata,
    ) -> UUID:
        assert metadata.request_id != metadata.correlation_id
        self.events.append(event)
        return uuid4()


def _line(
    company_id: UUID,
    key: str,
    *,
    received: str = "10",
    invoiced: str = "10",
    invoiced_price: str = "10",
) -> ThreeWayMatchLine:
    return ThreeWayMatchLine.create(
        company_id=company_id,
        match_key=key,
        purchase_order_item_id=uuid4(),
        goods_receipt_item_id=uuid4(),
        fiscal_document_item_id=uuid4(),
        ordered_quantity="10",
        received_quantity=received,
        invoiced_quantity=invoiced,
        ordered_unit_price="10",
        invoiced_unit_price=invoiced_price,
        currency="BRL",
    )


def _session(
    *,
    lines: tuple[ThreeWayMatchLine, ...] | None = None,
    company_id: UUID | None = None,
) -> ThreeWayMatchSession:
    company = company_id or uuid4()
    supplier = uuid4()
    return ThreeWayMatchSession.create(
        company_id=company,
        purchase_order_snapshot=PurchaseOrderMatchSnapshot.capture(
            company_id=company,
            purchase_order_id=uuid4(),
            purchase_order_version=2,
            supplier_id=supplier,
            currency="BRL",
            total_amount="100.00",
            captured_at=OCCURRED_AT,
        ),
        receiving_fiscal_snapshot=ReceivingFiscalMatchSnapshot.capture(
            company_id=company,
            goods_receipts=(VersionedArtifactReference(uuid4(), 1),),
            fiscal_documents=(VersionedArtifactReference(uuid4(), 1),),
            supplier_id=supplier,
            currency="BRL",
            invoiced_total_amount="100.00",
            captured_at=OCCURRED_AT,
        ),
        financial_snapshot=FinancialMatchSnapshot.capture(
            company_id=company,
            provisional_entry_id=uuid4(),
            provisional_entry_version=1,
            payable_id=uuid4(),
            payable_version=1,
            supplier_id=supplier,
            currency="BRL",
            obligation_amount="100.00",
            captured_at=OCCURRED_AT,
        ),
        tolerance_policy=MatchingTolerancePolicy.create(
            company_id=company,
            unit_price_variance_percentage="1",
            quantity_variance_percentage="1",
            rounding_absolute_limit="0.01",
        ),
        lines=lines or (_line(company, "MATCHED"),),
        created_by=uuid4(),
        created_at=OCCURRED_AT,
    )


def _command(aggregate: ThreeWayMatchSession) -> ExecuteThreeWayMatch:
    return ExecuteThreeWayMatch(
        company_id=aggregate.company_id,
        matching_session_id=aggregate.id,
        expected_version=aggregate.version,
        actor_id=aggregate.created_by,
        metadata=ProcurementCommandMetadata.new(),
        occurred_at=OCCURRED_AT,
    )


def test_service_executes_perfect_match_and_emits_completed_event() -> None:
    async def scenario() -> None:
        pending = _session()
        repository = FakeMatchingRepository(pending)
        events = CollectingMatchingEvents()
        result = await ThreeWayMatchingService(repository, events).execute(_command(pending))

        assert result.session.version == 3
        assert result.session.report is not None
        assert result.session.report.status is MatchStatus.MATCHED
        assert [value.version for value in repository.saves] == [2, 3]
        assert len(result.event_ids) == 1
        assert [event.event_type for event in events.events] == [MATCHING_SESSION_COMPLETED]
        assert events.events[0].payload["discrepancy_count"] == 0
        assert events.events[0].payload["line_count"] == 1

    asyncio.run(scenario())


def test_service_classifies_every_discrepancy_and_emits_explainable_event() -> None:
    async def scenario() -> None:
        company = uuid4()
        pending = _session(
            company_id=company,
            lines=(
                _line(company, "MATCHED", received="10.1"),
                _line(company, "PRICE", invoiced_price="10.12"),
                _line(company, "QUANTITY", received="9.8"),
                _line(company, "BOTH", received="9.8", invoiced_price="10.12"),
            ),
        )
        repository = FakeMatchingRepository(pending)
        events = CollectingMatchingEvents()
        result = await ThreeWayMatchingService(repository, events).execute(_command(pending))

        assert result.session.report is not None
        assert [value.status for value in result.session.report.lines] == [
            MatchStatus.MATCHED,
            MatchStatus.PRICE_MISMATCH,
            MatchStatus.QUANTITY_MISMATCH,
            MatchStatus.TOLERANCE_EXCEEDED,
        ]
        assert [event.event_type for event in events.events] == [
            MATCHING_SESSION_COMPLETED,
            MATCHING_DISCREPANCY_DETECTED,
        ]
        discrepancy = events.events[1].payload
        assert discrepancy["discrepancy_count"] == 3
        details = cast(list[dict[str, object]], discrepancy["discrepancies"])
        assert details[0]["reasons"] == ["UNIT_PRICE_TOLERANCE_EXCEEDED"]
        assert details[2]["reasons"] == [
            "QUANTITY_TOLERANCE_EXCEEDED",
            "UNIT_PRICE_TOLERANCE_EXCEEDED",
        ]
        assert details[2]["allowed_quantity_delta"] == str(Decimal("0.1000000000"))

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["missing", "foreign"])
def test_service_hides_missing_and_cross_tenant_sessions(mode: str) -> None:
    async def scenario() -> None:
        pending = _session()
        repository = FakeMatchingRepository(None if mode == "missing" else pending)
        command = _command(pending)
        if mode == "foreign":
            command = replace(command, company_id=uuid4())
        with pytest.raises(ApplicationError) as captured:
            await ThreeWayMatchingService(repository, CollectingMatchingEvents()).execute(command)
        assert captured.value.code == "RESOURCE_NOT_FOUND"

    asyncio.run(scenario())


def test_service_rejects_stale_or_non_pending_sessions() -> None:
    async def scenario() -> None:
        pending = _session()
        service = ThreeWayMatchingService(
            FakeMatchingRepository(pending), CollectingMatchingEvents()
        )
        with pytest.raises(ApplicationError) as stale:
            await service.execute(replace(_command(pending), expected_version=9))
        assert stale.value.code == "VERSION_CONFLICT"

        running = pending.start(occurred_at=OCCURRED_AT)
        with pytest.raises(ApplicationError) as state:
            await ThreeWayMatchingService(
                FakeMatchingRepository(running), CollectingMatchingEvents()
            ).execute(replace(_command(pending), expected_version=2))
        assert state.value.code == "BUSINESS_VALIDATION_ERROR"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("company_id", "invalid", "company_id"),
        ("matching_session_id", "invalid", "matching_session_id"),
        ("actor_id", "invalid", "actor_id"),
        ("expected_version", 0, "expected_version"),
        ("expected_version", True, "expected_version"),
        ("occurred_at", OCCURRED_AT.replace(tzinfo=None), "timezone-aware"),
    ],
)
def test_service_validates_command_contract(field: str, value: object, message: str) -> None:
    async def scenario() -> None:
        pending = _session()
        command = replace(_command(pending), **cast(Any, {field: value}))
        with pytest.raises(ValueError, match=message):
            await ThreeWayMatchingService(
                FakeMatchingRepository(pending), CollectingMatchingEvents()
            ).execute(command)

    asyncio.run(scenario())


def test_service_validates_command_type_and_translates_repository_errors() -> None:
    async def scenario() -> None:
        pending = _session()
        service = ThreeWayMatchingService(
            FakeMatchingRepository(pending), CollectingMatchingEvents()
        )
        with pytest.raises(TypeError, match="ExecuteThreeWayMatch"):
            await service.execute(cast(ExecuteThreeWayMatch, object()))

        conflicts = FakeMatchingRepository(pending)
        conflicts.fail_with = MatchingVersionConflictError("stale")
        with pytest.raises(ApplicationError) as conflict:
            await ThreeWayMatchingService(conflicts, CollectingMatchingEvents()).execute(
                _command(pending)
            )
        assert conflict.value.code == "VERSION_CONFLICT"

        invalid = FakeMatchingRepository(pending)
        invalid.fail_with = ValueError("invalid transition")
        with pytest.raises(ApplicationError) as validation:
            await ThreeWayMatchingService(invalid, CollectingMatchingEvents()).execute(
                _command(pending)
            )
        assert validation.value.code == "BUSINESS_VALIDATION_ERROR"
        assert validation.value.details[0].message == "invalid transition"

    asyncio.run(scenario())


def test_event_builder_requires_completed_terminal_session() -> None:
    pending = _session()
    with pytest.raises(ValueError, match="completed session report"):
        matching_execution_events(pending)
