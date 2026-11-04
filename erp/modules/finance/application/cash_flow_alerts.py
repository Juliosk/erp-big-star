"""Application orchestration for deterministic Cash Flow risk alerts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from erp.modules.finance.domain import (
    CashFlowAlertEngine,
    CashFlowAlertPolicy,
    CashFlowAlertSource,
    CashFlowExposure,
    CashFlowProjection,
    CashFlowRiskAlert,
)


@dataclass(frozen=True, slots=True)
class CashFlowAlertMetadata:
    actor_id: UUID | None
    request_id: UUID
    correlation_id: UUID
    detected_at: datetime
    source_ip: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("request_id", "correlation_id"):
            value = getattr(self, field_name)
            if not isinstance(value, UUID) or value.int == 0:
                raise ValueError(f"{field_name} must be a non-zero UUID.")
        if self.actor_id is not None and (
            not isinstance(self.actor_id, UUID) or self.actor_id.int == 0
        ):
            raise ValueError("actor_id must be a non-zero UUID when provided.")
        if (
            not isinstance(self.detected_at, datetime)
            or self.detected_at.tzinfo is None
            or self.detected_at.utcoffset() is None
        ):
            raise ValueError("detected_at must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class CashFlowAlertRecordResult:
    alert: CashFlowRiskAlert
    audit_id: UUID
    event_id: UUID


class CashFlowAlertRecorder(Protocol):
    async def record(
        self,
        alerts: tuple[CashFlowRiskAlert, ...],
        *,
        policy: CashFlowAlertPolicy,
        metadata: CashFlowAlertMetadata,
    ) -> tuple[CashFlowAlertRecordResult, ...]: ...


class CashFlowAlertService:
    """Evaluate one immutable snapshot and stage newly detected alerts."""

    def __init__(
        self,
        engine: CashFlowAlertEngine,
        recorder: CashFlowAlertRecorder,
    ) -> None:
        self._engine = engine
        self._recorder = recorder

    async def evaluate_and_record(
        self,
        projection: CashFlowProjection,
        *,
        source: CashFlowAlertSource,
        metadata: CashFlowAlertMetadata,
        exposures: tuple[CashFlowExposure, ...] = (),
    ) -> tuple[CashFlowAlertRecordResult, ...]:
        alerts = self._engine.evaluate(
            projection,
            source=source,
            exposures=exposures,
        )
        return await self._recorder.record(
            alerts,
            policy=self._engine.policy,
            metadata=metadata,
        )


__all__ = [
    "CashFlowAlertMetadata",
    "CashFlowAlertRecordResult",
    "CashFlowAlertRecorder",
    "CashFlowAlertService",
]
