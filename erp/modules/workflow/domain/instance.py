"""Workflow instances and active approval steps."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.workflow.domain.support import normalize_code, normalize_text, require_uuid


class WorkflowInstanceStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class WorkflowStepStatus(StrEnum):
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class WorkflowStepInstance:
    id: UUID
    company_id: UUID
    workflow_instance_id: UUID
    sequence: int
    code: str
    name: str
    required_permission: str
    status: WorkflowStepStatus
    activated_at: datetime | None
    decided_at: datetime | None
    decided_by: UUID | None
    version: int

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        workflow_instance_id: UUID,
        sequence: int,
        code: str,
        name: str,
        required_permission: str,
        active: bool = False,
    ) -> WorkflowStepInstance:
        if type(sequence) is not int or sequence < 1:
            raise ValueError("sequence must be a positive integer.")
        permission = required_permission.strip()
        if not permission or len(permission) > 120:
            raise ValueError("required_permission must be 1-120 characters.")
        return cls(
            id=uuid4(),
            company_id=require_uuid(company_id, "company_id"),
            workflow_instance_id=require_uuid(
                workflow_instance_id, "workflow_instance_id"
            ),
            sequence=sequence,
            code=normalize_code(code),
            name=normalize_text(name, "name", max_length=160),
            required_permission=permission,
            status=WorkflowStepStatus.ACTIVE if active else WorkflowStepStatus.WAITING,
            activated_at=datetime.now(UTC) if active else None,
            decided_at=None,
            decided_by=None,
            version=1,
        )

    def approve(self, *, actor_id: UUID, now: datetime | None = None) -> WorkflowStepInstance:
        return self._decide(
            actor_id=actor_id,
            status=WorkflowStepStatus.APPROVED,
            now=now,
        )

    def reject(self, *, actor_id: UUID, now: datetime | None = None) -> WorkflowStepInstance:
        return self._decide(
            actor_id=actor_id,
            status=WorkflowStepStatus.REJECTED,
            now=now,
        )

    def activate(self, *, now: datetime | None = None) -> WorkflowStepInstance:
        if self.status is not WorkflowStepStatus.WAITING:
            raise ValueError("Only waiting workflow steps can be activated.")
        return WorkflowStepInstance(
            id=self.id,
            company_id=self.company_id,
            workflow_instance_id=self.workflow_instance_id,
            sequence=self.sequence,
            code=self.code,
            name=self.name,
            required_permission=self.required_permission,
            status=WorkflowStepStatus.ACTIVE,
            activated_at=now or datetime.now(UTC),
            decided_at=None,
            decided_by=None,
            version=self.version + 1,
        )

    def _decide(
        self,
        *,
        actor_id: UUID,
        status: WorkflowStepStatus,
        now: datetime | None,
    ) -> WorkflowStepInstance:
        require_uuid(actor_id, "actor_id")
        if self.status is not WorkflowStepStatus.ACTIVE:
            raise ValueError("Only active workflow steps can be decided.")
        return WorkflowStepInstance(
            id=self.id,
            company_id=self.company_id,
            workflow_instance_id=self.workflow_instance_id,
            sequence=self.sequence,
            code=self.code,
            name=self.name,
            required_permission=self.required_permission,
            status=status,
            activated_at=self.activated_at,
            decided_at=now or datetime.now(UTC),
            decided_by=actor_id,
            version=self.version + 1,
        )


@dataclass(frozen=True, slots=True)
class WorkflowInstance:
    id: UUID
    company_id: UUID
    definition_id: UUID
    source_module: str
    source_type: str
    source_id: UUID
    source_fingerprint: str
    status: WorkflowInstanceStatus
    current_step_sequence: int | None
    requested_by: UUID
    version: int

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        definition_id: UUID,
        source_module: str,
        source_type: str,
        source_id: UUID,
        source_fingerprint: str,
        requested_by: UUID,
    ) -> WorkflowInstance:
        fingerprint = source_fingerprint.strip()
        if not fingerprint or len(fingerprint) > 128:
            raise ValueError("source_fingerprint must be 1-128 characters.")
        return cls(
            id=uuid4(),
            company_id=require_uuid(company_id, "company_id"),
            definition_id=require_uuid(definition_id, "definition_id"),
            source_module=normalize_code(source_module, "source_module", max_length=32),
            source_type=normalize_code(source_type, "source_type", max_length=64),
            source_id=require_uuid(source_id, "source_id"),
            source_fingerprint=fingerprint,
            status=WorkflowInstanceStatus.PENDING,
            current_step_sequence=1,
            requested_by=require_uuid(requested_by, "requested_by"),
            version=1,
        )

    def approve_final(self) -> WorkflowInstance:
        if self.status is not WorkflowInstanceStatus.PENDING:
            raise ValueError("Only pending workflow instances can be approved.")
        return self._replace(status=WorkflowInstanceStatus.APPROVED, current_step_sequence=None)

    def reject_final(self) -> WorkflowInstance:
        if self.status is not WorkflowInstanceStatus.PENDING:
            raise ValueError("Only pending workflow instances can be rejected.")
        return self._replace(status=WorkflowInstanceStatus.REJECTED, current_step_sequence=None)

    def advance_to(self, sequence: int) -> WorkflowInstance:
        if self.status is not WorkflowInstanceStatus.PENDING:
            raise ValueError("Only pending workflow instances can advance.")
        if type(sequence) is not int or sequence < 1:
            raise ValueError("sequence must be a positive integer.")
        return self._replace(status=WorkflowInstanceStatus.PENDING, current_step_sequence=sequence)

    def _replace(
        self,
        *,
        status: WorkflowInstanceStatus,
        current_step_sequence: int | None,
    ) -> WorkflowInstance:
        return WorkflowInstance(
            id=self.id,
            company_id=self.company_id,
            definition_id=self.definition_id,
            source_module=self.source_module,
            source_type=self.source_type,
            source_id=self.source_id,
            source_fingerprint=self.source_fingerprint,
            status=status,
            current_step_sequence=current_step_sequence,
            requested_by=self.requested_by,
            version=self.version + 1,
        )


__all__ = [
    "WorkflowInstance",
    "WorkflowInstanceStatus",
    "WorkflowStepInstance",
    "WorkflowStepStatus",
]
