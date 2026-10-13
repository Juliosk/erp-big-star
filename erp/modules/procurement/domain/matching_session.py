"""Pure M6 aggregate controlling a three-way matching execution."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self, cast
from uuid import UUID, uuid4

from erp.modules.procurement.domain.exceptions import (
    InvalidMatchingSessionError,
    InvalidMatchingTransitionError,
    MatchingScopeError,
)
from erp.modules.procurement.domain.matching import (
    MatchingTolerancePolicy,
    ThreeWayMatchLine,
    ThreeWayMatchReport,
    compare_lines,
)
from erp.modules.procurement.domain.matching_snapshots import (
    FinancialMatchSnapshot,
    PurchaseOrderMatchSnapshot,
    ReceivingFiscalMatchSnapshot,
)


class ThreeWayMatchSessionStatus(StrEnum):
    """Lifecycle states for one immutable three-way matching execution."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    MATCHED = "MATCHED"
    DISCREPANCY_DETECTED = "DISCREPANCY_DETECTED"
    OVERRIDDEN = "OVERRIDDEN"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ThreeWayMatchSession:
    """Aggregate that freezes sources and controls one matching lifecycle."""

    id: UUID
    company_id: UUID
    purchase_order_snapshot: PurchaseOrderMatchSnapshot
    receiving_fiscal_snapshot: ReceivingFiscalMatchSnapshot
    financial_snapshot: FinancialMatchSnapshot
    tolerance_policy: MatchingTolerancePolicy
    lines: tuple[ThreeWayMatchLine, ...]
    status: ThreeWayMatchSessionStatus
    created_by: UUID
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    report: ThreeWayMatchReport | None
    decision_by: UUID | None
    decision_workflow_instance_id: UUID | None
    decision_reason: str | None
    decided_at: datetime | None
    version: int

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        purchase_order_snapshot: PurchaseOrderMatchSnapshot,
        receiving_fiscal_snapshot: ReceivingFiscalMatchSnapshot,
        financial_snapshot: FinancialMatchSnapshot,
        tolerance_policy: MatchingTolerancePolicy,
        lines: tuple[ThreeWayMatchLine, ...],
        created_by: UUID,
        created_at: datetime | None = None,
        session_id: UUID | None = None,
    ) -> Self:
        return cls(
            id=session_id or uuid4(),
            company_id=company_id,
            purchase_order_snapshot=purchase_order_snapshot,
            receiving_fiscal_snapshot=receiving_fiscal_snapshot,
            financial_snapshot=financial_snapshot,
            tolerance_policy=tolerance_policy,
            lines=lines,
            status=ThreeWayMatchSessionStatus.PENDING,
            created_by=created_by,
            created_at=created_at or datetime.now(UTC),
            started_at=None,
            completed_at=None,
            report=None,
            decision_by=None,
            decision_workflow_instance_id=None,
            decision_reason=None,
            decided_at=None,
            version=1,
        )

    def __post_init__(self) -> None:
        _uuid(self.id, "session id")
        _uuid(self.company_id, "company_id")
        _uuid(self.created_by, "created_by")
        if type(self.version) is not int or self.version < 1:
            raise InvalidMatchingSessionError("version must be a positive integer.")
        if not isinstance(self.status, ThreeWayMatchSessionStatus):
            raise InvalidMatchingSessionError("status must be a ThreeWayMatchSessionStatus.")
        if not isinstance(self.purchase_order_snapshot, PurchaseOrderMatchSnapshot):
            raise InvalidMatchingSessionError(
                "purchase_order_snapshot must be a PurchaseOrderMatchSnapshot."
            )
        if not isinstance(self.receiving_fiscal_snapshot, ReceivingFiscalMatchSnapshot):
            raise InvalidMatchingSessionError(
                "receiving_fiscal_snapshot must be a ReceivingFiscalMatchSnapshot."
            )
        if not isinstance(self.financial_snapshot, FinancialMatchSnapshot):
            raise InvalidMatchingSessionError(
                "financial_snapshot must be a FinancialMatchSnapshot."
            )
        if not isinstance(self.tolerance_policy, MatchingTolerancePolicy):
            raise InvalidMatchingSessionError("tolerance_policy must be a MatchingTolerancePolicy.")
        _session_lines(self.lines)
        _timestamp(self.created_at, "created_at", InvalidMatchingSessionError)
        self._validate_scope()
        self._validate_lifecycle()

    def start(self, *, occurred_at: datetime | None = None) -> Self:
        if self.status is not ThreeWayMatchSessionStatus.PENDING:
            raise InvalidMatchingTransitionError("only a pending session can start.")
        started_at = _transition_time(occurred_at, self.created_at, "started_at")
        return replace(
            self,
            status=ThreeWayMatchSessionStatus.RUNNING,
            started_at=started_at,
            version=self.version + 1,
        )

    def evaluate(self, *, occurred_at: datetime | None = None) -> Self:
        if self.status is not ThreeWayMatchSessionStatus.RUNNING:
            raise InvalidMatchingTransitionError("only a running session can be evaluated.")
        started_at = cast(datetime, self.started_at)
        completed_at = _transition_time(occurred_at, started_at, "completed_at")
        report = compare_lines(self.lines, self.tolerance_policy)
        status = (
            ThreeWayMatchSessionStatus.MATCHED
            if report.matched
            else ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED
        )
        return replace(
            self,
            status=status,
            completed_at=completed_at,
            report=report,
            version=self.version + 1,
        )

    def override(
        self,
        *,
        decided_by: UUID,
        workflow_instance_id: UUID,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> Self:
        return self._decide(
            ThreeWayMatchSessionStatus.OVERRIDDEN,
            decided_by=decided_by,
            workflow_instance_id=workflow_instance_id,
            reason=reason,
            occurred_at=occurred_at,
        )

    def reject(
        self,
        *,
        decided_by: UUID,
        workflow_instance_id: UUID,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> Self:
        return self._decide(
            ThreeWayMatchSessionStatus.REJECTED,
            decided_by=decided_by,
            workflow_instance_id=workflow_instance_id,
            reason=reason,
            occurred_at=occurred_at,
        )

    def _decide(
        self,
        status: ThreeWayMatchSessionStatus,
        *,
        decided_by: UUID,
        workflow_instance_id: UUID,
        reason: str,
        occurred_at: datetime | None,
    ) -> Self:
        if self.status is not ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED:
            raise InvalidMatchingTransitionError(
                "only a discrepancy session can be overridden or rejected."
            )
        completed_at = cast(datetime, self.completed_at)
        _uuid(decided_by, "decided_by")
        _uuid(workflow_instance_id, "decision_workflow_instance_id")
        decision_reason = _reason(reason)
        decided_at = _transition_time(occurred_at, completed_at, "decided_at")
        return replace(
            self,
            status=status,
            decision_by=decided_by,
            decision_workflow_instance_id=workflow_instance_id,
            decision_reason=decision_reason,
            decided_at=decided_at,
            version=self.version + 1,
        )

    def _validate_scope(self) -> None:
        snapshots = (
            self.purchase_order_snapshot,
            self.receiving_fiscal_snapshot,
            self.financial_snapshot,
        )
        if self.tolerance_policy.company_id != self.company_id or any(
            snapshot.company_id != self.company_id for snapshot in snapshots
        ):
            raise MatchingScopeError(
                "session, policy and snapshots must belong to the same company."
            )
        if any(line.company_id != self.company_id for line in self.lines):
            raise MatchingScopeError("every match line must belong to the session company.")
        if len({snapshot.supplier_id for snapshot in snapshots}) != 1:
            raise InvalidMatchingSessionError(
                "purchase, fiscal and financial snapshots must identify one supplier."
            )
        currencies = {snapshot.currency for snapshot in snapshots}
        currencies.update(line.currency for line in self.lines)
        if len(currencies) != 1:
            raise InvalidMatchingSessionError("snapshots and match lines must use one currency.")
        latest_capture = max(snapshot.captured_at for snapshot in snapshots)
        if self.created_at < latest_capture:
            raise InvalidMatchingSessionError(
                "created_at cannot precede a source snapshot capture."
            )

    def _validate_lifecycle(self) -> None:
        if self.status is ThreeWayMatchSessionStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.started_at,
                    self.completed_at,
                    self.report,
                    self.decision_by,
                    self.decision_workflow_instance_id,
                    self.decision_reason,
                    self.decided_at,
                )
            ):
                raise InvalidMatchingSessionError(
                    "pending session cannot contain execution or decision data."
                )
            return
        if self.started_at is None:
            raise InvalidMatchingSessionError("non-pending session requires started_at.")
        _timestamp(self.started_at, "started_at", InvalidMatchingSessionError)
        if self.started_at < self.created_at:
            raise InvalidMatchingSessionError("started_at cannot precede created_at.")
        if self.status is ThreeWayMatchSessionStatus.RUNNING:
            if any(
                value is not None
                for value in (
                    self.completed_at,
                    self.report,
                    self.decision_by,
                    self.decision_workflow_instance_id,
                    self.decision_reason,
                    self.decided_at,
                )
            ):
                raise InvalidMatchingSessionError(
                    "running session cannot contain result or decision data."
                )
            return
        self._validate_completed_lifecycle()

    def _validate_completed_lifecycle(self) -> None:
        if self.completed_at is None or not isinstance(self.report, ThreeWayMatchReport):
            raise InvalidMatchingSessionError("completed session requires completed_at and report.")
        _timestamp(self.completed_at, "completed_at", InvalidMatchingSessionError)
        if self.completed_at < cast(datetime, self.started_at):
            raise InvalidMatchingSessionError("completed_at cannot precede started_at.")
        if self.report.company_id != self.company_id:
            raise MatchingScopeError("match report must belong to the session company.")
        if (
            self.report.policy != self.tolerance_policy
            or tuple(result.line for result in self.report.lines) != self.lines
        ):
            raise InvalidMatchingSessionError(
                "match report must be derived from the frozen session inputs."
            )
        expected_status = (
            ThreeWayMatchSessionStatus.MATCHED
            if self.report.matched
            else ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED
        )
        if self.status in (
            ThreeWayMatchSessionStatus.MATCHED,
            ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED,
        ):
            if self.status is not expected_status:
                raise InvalidMatchingSessionError(
                    "completed status does not match the calculated report."
                )
            if any(
                value is not None
                for value in (
                    self.decision_by,
                    self.decision_workflow_instance_id,
                    self.decision_reason,
                    self.decided_at,
                )
            ):
                raise InvalidMatchingSessionError(
                    "undecided completed session cannot contain decision data."
                )
            return
        if expected_status is not ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED:
            raise InvalidMatchingSessionError(
                "only a discrepancy report can be overridden or rejected."
            )
        if (
            self.decision_by is None
            or self.decision_workflow_instance_id is None
            or self.decision_reason is None
            or self.decided_at is None
        ):
            raise InvalidMatchingSessionError(
                "final decision requires actor, workflow, reason and timestamp."
            )
        _uuid(self.decision_by, "decision_by")
        _uuid(self.decision_workflow_instance_id, "decision_workflow_instance_id")
        _reason(self.decision_reason)
        _timestamp(self.decided_at, "decided_at", InvalidMatchingSessionError)
        if self.decided_at < self.completed_at:
            raise InvalidMatchingSessionError("decided_at cannot precede completed_at.")


def _session_lines(lines: tuple[ThreeWayMatchLine, ...]) -> None:
    if not isinstance(lines, tuple) or not lines:
        raise InvalidMatchingSessionError("lines must be a non-empty tuple.")
    if any(not isinstance(line, ThreeWayMatchLine) for line in lines):
        raise InvalidMatchingSessionError("every line must be a ThreeWayMatchLine.")
    keys = tuple(line.match_key for line in lines)
    if len(set(keys)) != len(keys):
        raise InvalidMatchingSessionError("match_key must be unique inside the session.")


def _uuid(value: object, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise InvalidMatchingSessionError(f"{field} must be a UUID.")
    return value


def _timestamp(value: datetime, field: str, error_type: type[ValueError]) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise error_type(f"{field} must be timezone-aware.")
    return value


def _transition_time(occurred_at: datetime | None, floor: datetime, field: str) -> datetime:
    value = occurred_at or datetime.now(UTC)
    _timestamp(value, field, InvalidMatchingTransitionError)
    if value < floor:
        raise InvalidMatchingTransitionError(f"{field} cannot precede the prior transition.")
    return value


def _reason(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidMatchingSessionError("decision reason must be text.")
    normalized = " ".join(value.split())
    if not 10 <= len(normalized) <= 500:
        raise InvalidMatchingSessionError("decision reason must contain 10 to 500 characters.")
    return normalized


__all__ = ["ThreeWayMatchSession", "ThreeWayMatchSessionStatus"]
