"""Workflow definitions and sequential approval policies."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.workflow.domain.support import (
    normalize_amount,
    normalize_code,
    normalize_text,
    require_uuid,
)


class ApprovalMode(StrEnum):
    SEQUENTIAL = "SEQUENTIAL"
    HIGHEST_LEVEL = "HIGHEST_LEVEL"
    CUMULATIVE = "CUMULATIVE"


@dataclass(frozen=True, slots=True)
class WorkflowStepDefinition:
    id: UUID
    company_id: UUID
    sequence: int
    code: str
    name: str
    required_permission: str
    threshold_amount: Decimal | None

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        sequence: int,
        code: str,
        name: str,
        required_permission: str,
        threshold_amount: Decimal | str | None = None,
    ) -> WorkflowStepDefinition:
        if type(sequence) is not int or sequence < 1:
            raise ValueError("sequence must be a positive integer.")
        permission = required_permission.strip()
        if not permission or len(permission) > 120:
            raise ValueError("required_permission must be 1-120 characters.")
        return cls(
            id=uuid4(),
            company_id=require_uuid(company_id, "company_id"),
            sequence=sequence,
            code=normalize_code(code),
            name=normalize_text(name, "name", max_length=160),
            required_permission=permission,
            threshold_amount=normalize_amount(threshold_amount),
        )


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    id: UUID
    company_id: UUID
    code: str
    name: str
    source_module: str
    source_type: str
    approval_mode: ApprovalMode
    active: bool
    version: int

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        code: str,
        name: str,
        source_module: str,
        source_type: str,
        approval_mode: ApprovalMode = ApprovalMode.SEQUENTIAL,
    ) -> WorkflowDefinition:
        if not isinstance(approval_mode, ApprovalMode):
            raise ValueError("approval_mode must be a valid ApprovalMode.")
        return cls(
            id=uuid4(),
            company_id=require_uuid(company_id, "company_id"),
            code=normalize_code(code),
            name=normalize_text(name, "name", max_length=160),
            source_module=normalize_code(source_module, "source_module", max_length=32),
            source_type=normalize_code(source_type, "source_type", max_length=64),
            approval_mode=approval_mode,
            active=True,
            version=1,
        )

    def deactivate(self) -> WorkflowDefinition:
        if not self.active:
            raise ValueError("Workflow definition is already inactive.")
        return WorkflowDefinition(
            id=self.id,
            company_id=self.company_id,
            code=self.code,
            name=self.name,
            source_module=self.source_module,
            source_type=self.source_type,
            approval_mode=self.approval_mode,
            active=False,
            version=self.version + 1,
        )


__all__ = ["ApprovalMode", "WorkflowDefinition", "WorkflowStepDefinition"]
