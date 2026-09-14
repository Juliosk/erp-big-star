"""Formal approval decision records for M22."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.workflow.domain.support import normalize_code, require_uuid


class ApprovalDecisionKind(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    id: UUID
    company_id: UUID
    workflow_instance_id: UUID
    step_instance_id: UUID
    decision: ApprovalDecisionKind
    decided_by: UUID
    decided_at: datetime
    reason_code: str | None
    comment: str | None

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        workflow_instance_id: UUID,
        step_instance_id: UUID,
        decision: ApprovalDecisionKind,
        decided_by: UUID,
        reason_code: str | None = None,
        comment: str | None = None,
        now: datetime | None = None,
    ) -> ApprovalDecision:
        if not isinstance(decision, ApprovalDecisionKind):
            raise ValueError("decision must be a valid approval decision.")
        normalized_comment = None if comment is None else comment.strip()
        if normalized_comment is not None and len(normalized_comment) > 500:
            raise ValueError("comment must be at most 500 characters.")
        return cls(
            id=uuid4(),
            company_id=require_uuid(company_id, "company_id"),
            workflow_instance_id=require_uuid(
                workflow_instance_id, "workflow_instance_id"
            ),
            step_instance_id=require_uuid(step_instance_id, "step_instance_id"),
            decision=decision,
            decided_by=require_uuid(decided_by, "decided_by"),
            decided_at=now or datetime.now(UTC),
            reason_code=(
                None
                if reason_code is None
                else normalize_code(reason_code, "reason_code", max_length=64)
            ),
            comment=normalized_comment or None,
        )


__all__ = ["ApprovalDecision", "ApprovalDecisionKind"]
