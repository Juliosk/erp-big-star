"""Application boundary for governed three-way matching overrides."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.procurement.application.purchasing import ProcurementCommandMetadata
from erp.modules.procurement.domain import ThreeWayMatchSession


class MatchingOverrideDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class RequestMatchingOverride:
    company_id: UUID
    matching_session_id: UUID
    expected_version: int
    justification: str
    idempotency_key: str
    metadata: ProcurementCommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "matching_session_id": str(self.matching_session_id),
            "expected_version": self.expected_version,
            "justification": self.justification,
        }


@dataclass(frozen=True, slots=True)
class DecideMatchingOverride:
    company_id: UUID
    matching_session_id: UUID
    expected_version: int
    workflow_instance_id: UUID
    workflow_step_instance_id: UUID
    workflow_expected_version: int
    decision: MatchingOverrideDecision
    reason: str
    idempotency_key: str
    metadata: ProcurementCommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "matching_session_id": str(self.matching_session_id),
            "expected_version": self.expected_version,
            "workflow_instance_id": str(self.workflow_instance_id),
            "workflow_step_instance_id": str(self.workflow_step_instance_id),
            "workflow_expected_version": self.workflow_expected_version,
            "decision": self.decision.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class MatchingWorkflowStepView:
    id: UUID
    sequence: int
    code: str
    name: str
    required_permission: str
    status: str
    version: int


@dataclass(frozen=True, slots=True)
class MatchingWorkflowView:
    id: UUID
    status: str
    version: int
    discrepancy_amount: Decimal
    requested_by: UUID
    steps: tuple[MatchingWorkflowStepView, ...]


@dataclass(frozen=True, slots=True)
class MatchingGovernanceResult:
    session: ThreeWayMatchSession
    workflow: MatchingWorkflowView
    event_ids: tuple[UUID, ...]


class MatchingGovernanceStore(Protocol):
    async def request_override(
        self,
        command: RequestMatchingOverride,
        *,
        actor_id: UUID,
        actor_permissions: frozenset[str],
    ) -> MatchingGovernanceResult: ...

    async def decide_override(
        self,
        command: DecideMatchingOverride,
        *,
        actor_id: UUID,
        actor_permissions: frozenset[str],
    ) -> MatchingGovernanceResult: ...


class MatchingGovernanceAuthorization(Protocol):
    async def require_request(self, context: SecurityContext, company_id: UUID) -> None: ...

    async def require_decision(self, context: SecurityContext, company_id: UUID) -> None: ...


class MatchingGovernanceService:
    """Authorize override commands and dispatch them to one atomic store."""

    def __init__(
        self,
        store: MatchingGovernanceStore,
        authorization: MatchingGovernanceAuthorization,
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def request_override(
        self,
        context: SecurityContext,
        command: RequestMatchingOverride,
    ) -> MatchingGovernanceResult:
        await self._authorization.require_request(context, command.company_id)
        return await self._store.request_override(
            command,
            actor_id=context.principal.user_id,
            actor_permissions=_permissions(context),
        )

    async def decide_override(
        self,
        context: SecurityContext,
        command: DecideMatchingOverride,
    ) -> MatchingGovernanceResult:
        await self._authorization.require_decision(context, command.company_id)
        return await self._store.decide_override(
            command,
            actor_id=context.principal.user_id,
            actor_permissions=_permissions(context),
        )


def normalize_override_reason(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text.")
    normalized = " ".join(value.split())
    if not 10 <= len(normalized) <= 500:
        raise ValueError(f"{field} must contain 10 to 500 characters.")
    return normalized


def validate_governance_version(value: int, *, field: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} must be a positive integer.")


def validate_governance_timestamp(value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("occurred_at must be timezone-aware.")


def _permissions(context: SecurityContext) -> frozenset[str]:
    return frozenset(str(permission) for permission in context.permissions)


__all__ = [
    "DecideMatchingOverride",
    "MatchingGovernanceAuthorization",
    "MatchingGovernanceResult",
    "MatchingGovernanceService",
    "MatchingGovernanceStore",
    "MatchingOverrideDecision",
    "MatchingWorkflowStepView",
    "MatchingWorkflowView",
    "RequestMatchingOverride",
    "normalize_override_reason",
    "validate_governance_timestamp",
    "validate_governance_version",
]
