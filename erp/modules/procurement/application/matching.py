"""Application orchestration for deterministic M6 three-way matching."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from erp.modules.procurement.application.purchasing import ProcurementCommandMetadata
from erp.modules.procurement.domain import (
    LineMatchResult,
    MatchingVersionConflictError,
    ThreeWayMatchSession,
    ThreeWayMatchSessionStatus,
)
from erp.platform.errors import ApplicationError, ErrorDetail

MATCHING_SESSION_COMPLETED = "MatchingSessionCompleted"
MATCHING_DISCREPANCY_DETECTED = "MatchingDiscrepancyDetected"


@dataclass(frozen=True, slots=True)
class ExecuteThreeWayMatch:
    """Tenant-scoped command for one pending matching session."""

    company_id: UUID
    matching_session_id: UUID
    expected_version: int
    actor_id: UUID
    metadata: ProcurementCommandMetadata
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MatchingExecutionEvent:
    """Transport-neutral domain event staged after a completed execution."""

    event_type: str
    aggregate: ThreeWayMatchSession
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class MatchingExecutionResult:
    session: ThreeWayMatchSession
    event_ids: tuple[UUID, ...]


class MatchingSessionRepository(Protocol):
    """Minimal persistence contract required by the application service."""

    async def get(self, matching_session_id: UUID) -> ThreeWayMatchSession | None: ...

    async def save(
        self,
        aggregate: ThreeWayMatchSession,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> ThreeWayMatchSession: ...


class MatchingEventPublisher(Protocol):
    """Stage matching events inside the caller-owned transaction."""

    async def publish(
        self,
        event: MatchingExecutionEvent,
        *,
        metadata: ProcurementCommandMetadata,
    ) -> UUID: ...


class ThreeWayMatchingService:
    """Run the pure engine and stage persistence/audit/outbox effects atomically."""

    def __init__(
        self,
        repository: MatchingSessionRepository,
        events: MatchingEventPublisher,
    ) -> None:
        self._repository = repository
        self._events = events

    async def execute(self, command: ExecuteThreeWayMatch) -> MatchingExecutionResult:
        _validate_command(command)
        current = await self._repository.get(command.matching_session_id)
        if current is None or current.company_id != command.company_id:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Three-way matching session not found.",
                status_code=404,
            )
        if current.version != command.expected_version:
            raise _version_conflict(command.expected_version)
        if current.status is not ThreeWayMatchSessionStatus.PENDING:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Only a pending three-way matching session can be executed.",
                status_code=422,
            )

        occurred_at = command.occurred_at or datetime.now(UTC)
        try:
            running = current.start(occurred_at=occurred_at)
            await self._repository.save(
                running,
                actor_id=command.actor_id,
                expected_version=current.version,
            )
            completed = running.evaluate(occurred_at=occurred_at)
            completed = await self._repository.save(
                completed,
                actor_id=command.actor_id,
                expected_version=running.version,
            )
        except MatchingVersionConflictError as error:
            raise _version_conflict(command.expected_version) from error
        except ValueError as error:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Three-way matching execution failed domain validation.",
                status_code=422,
                details=[ErrorDetail(message=str(error))],
            ) from error

        event_ids = tuple(
            [
                await self._events.publish(event, metadata=command.metadata)
                for event in matching_execution_events(completed)
            ]
        )
        return MatchingExecutionResult(completed, event_ids)


def matching_execution_events(
    aggregate: ThreeWayMatchSession,
) -> tuple[MatchingExecutionEvent, ...]:
    """Build stable, explainable events from an evaluated aggregate."""
    if aggregate.report is None or aggregate.completed_at is None:
        raise ValueError("Matching events require a completed session report.")

    line_results = tuple(_line_result_payload(result) for result in aggregate.report.lines)
    discrepancies = tuple(
        result for result in line_results if result["status"] != "MATCHED"
    )
    common: dict[str, object] = {
        "company_id": str(aggregate.company_id),
        "matching_session_id": str(aggregate.id),
        "status": aggregate.status.value,
        "report_status": aggregate.report.status.value,
        "aggregate_version": aggregate.version,
        "completed_at": aggregate.completed_at.isoformat(),
        "purchase_order_id": str(
            aggregate.purchase_order_snapshot.purchase_order.id
        ),
        "goods_receipt_ids": [
            str(reference.id)
            for reference in aggregate.receiving_fiscal_snapshot.goods_receipts
        ],
        "inbound_fiscal_document_ids": [
            str(reference.id)
            for reference in aggregate.receiving_fiscal_snapshot.fiscal_documents
        ],
        "provisional_entry_id": str(
            aggregate.financial_snapshot.provisional_entry.id
        ),
        "payable_id": (
            str(aggregate.financial_snapshot.payable.id)
            if aggregate.financial_snapshot.payable is not None
            else None
        ),
        "line_count": len(line_results),
        "discrepancy_count": len(discrepancies),
        "line_results": list(line_results),
    }
    events = [
        MatchingExecutionEvent(
            event_type=MATCHING_SESSION_COMPLETED,
            aggregate=aggregate,
            payload=common,
        )
    ]
    if discrepancies:
        events.append(
            MatchingExecutionEvent(
                event_type=MATCHING_DISCREPANCY_DETECTED,
                aggregate=aggregate,
                payload={**common, "discrepancies": list(discrepancies)},
            )
        )
    return tuple(events)


def _line_result_payload(result: LineMatchResult) -> dict[str, object]:
    return {
        "match_key": result.line.match_key,
        "status": result.status.value,
        "quantity_delta": str(result.quantity_delta),
        "unit_price_delta": str(result.unit_price_delta),
        "allowed_quantity_delta": str(result.allowed_quantity_delta),
        "allowed_unit_price_delta": str(result.allowed_unit_price_delta),
        "reasons": list(result.reasons),
    }


def _validate_command(command: ExecuteThreeWayMatch) -> None:
    if not isinstance(command, ExecuteThreeWayMatch):
        raise TypeError("command must be an ExecuteThreeWayMatch.")
    for field, value in (
        ("company_id", command.company_id),
        ("matching_session_id", command.matching_session_id),
        ("actor_id", command.actor_id),
    ):
        if not isinstance(value, UUID):
            raise ValueError(f"{field} must be a UUID.")
    if type(command.expected_version) is not int or command.expected_version < 1:
        raise ValueError("expected_version must be a positive integer.")
    if command.occurred_at is not None and (
        not isinstance(command.occurred_at, datetime)
        or command.occurred_at.tzinfo is None
        or command.occurred_at.utcoffset() is None
    ):
        raise ValueError("occurred_at must be timezone-aware.")


def _version_conflict(expected_version: int) -> ApplicationError:
    return ApplicationError(
        code="VERSION_CONFLICT",
        message="The matching session was changed by another transaction.",
        status_code=409,
        details=[ErrorDetail(message=f"Expected version {expected_version} is stale.")],
    )


__all__ = [
    "MATCHING_DISCREPANCY_DETECTED",
    "MATCHING_SESSION_COMPLETED",
    "ExecuteThreeWayMatch",
    "MatchingEventPublisher",
    "MatchingExecutionEvent",
    "MatchingExecutionResult",
    "MatchingSessionRepository",
    "ThreeWayMatchingService",
    "matching_execution_events",
]
