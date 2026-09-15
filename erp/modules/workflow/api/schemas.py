"""Public Workflow Core request and response schemas."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.workflow.domain import (
    ApprovalDecisionKind,
    ApprovalMode,
    WorkflowInstanceStatus,
    WorkflowStepStatus,
)


class PageMetadata(BaseModel):
    page: int
    page_size: int
    has_more: bool


class WorkflowStepDefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    required_permission: str = Field(min_length=1, max_length=120)
    threshold_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)


class CreateWorkflowDefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    source_module: str = Field(min_length=1, max_length=32)
    source_type: str = Field(min_length=1, max_length=64)
    approval_mode: ApprovalMode = ApprovalMode.SEQUENTIAL
    steps: list[WorkflowStepDefinitionRequest] = Field(min_length=1, max_length=20)


class WorkflowDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    source_module: str
    source_type: str
    approval_mode: ApprovalMode
    active: bool
    version: int


class WorkflowStepDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    sequence: int
    code: str
    name: str
    required_permission: str
    threshold_amount: str | None


class WorkflowDefinitionDetailResponse(BaseModel):
    definition: WorkflowDefinitionResponse
    steps: list[WorkflowStepDefinitionResponse]


class WorkflowDefinitionListResponse(BaseModel):
    data: list[WorkflowDefinitionResponse]
    meta: PageMetadata


class CreateWorkflowInstanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    source_module: str = Field(min_length=1, max_length=32)
    source_type: str = Field(min_length=1, max_length=64)
    source_id: UUID
    source_fingerprint: str = Field(min_length=1, max_length=128)


class DecideWorkflowInstanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    step_instance_id: UUID
    decision: ApprovalDecisionKind
    reason_code: str | None = Field(default=None, min_length=1, max_length=64)
    comment: str | None = Field(default=None, max_length=500)


class WorkflowStepInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    workflow_instance_id: UUID
    sequence: int
    code: str
    name: str
    required_permission: str
    status: WorkflowStepStatus
    activated_at: str | None
    decided_at: str | None
    decided_by: UUID | None
    version: int


class WorkflowInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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


class WorkflowInstanceDetailResponse(BaseModel):
    instance: WorkflowInstanceResponse
    steps: list[WorkflowStepInstanceResponse]


class PendingApprovalResponse(BaseModel):
    step: WorkflowStepInstanceResponse
    instance: WorkflowInstanceResponse


class PendingApprovalListResponse(BaseModel):
    data: list[PendingApprovalResponse]
    meta: PageMetadata


class ApprovalDecisionResponse(BaseModel):
    id: UUID
    company_id: UUID
    workflow_instance_id: UUID
    step_instance_id: UUID
    decision: ApprovalDecisionKind
    decided_by: UUID
    decided_at: str
    reason_code: str | None
    comment: str | None


class WorkflowDecisionResponse(BaseModel):
    detail: WorkflowInstanceDetailResponse
    decision: ApprovalDecisionResponse
    event_id: UUID | None = None
    audit_event_id: UUID | None = None


__all__ = [
    "ApprovalDecisionResponse",
    "CreateWorkflowDefinitionRequest",
    "CreateWorkflowInstanceRequest",
    "DecideWorkflowInstanceRequest",
    "PageMetadata",
    "PendingApprovalListResponse",
    "PendingApprovalResponse",
    "WorkflowDecisionResponse",
    "WorkflowDefinitionDetailResponse",
    "WorkflowDefinitionListResponse",
    "WorkflowDefinitionResponse",
    "WorkflowInstanceDetailResponse",
    "WorkflowInstanceResponse",
    "WorkflowStepDefinitionRequest",
    "WorkflowStepDefinitionResponse",
    "WorkflowStepInstanceResponse",
]
