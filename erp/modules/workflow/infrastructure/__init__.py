"""Internal M22 persistence adapters, wired only at the composition boundary."""

from erp.modules.workflow.infrastructure.approvals import PostgresWorkflowApprovals
from erp.modules.workflow.infrastructure.decisions import (
    PostgresWorkflowDecisions,
    apply_workflow_decision,
)
from erp.modules.workflow.infrastructure.definitions import PostgresWorkflowDefinitions
from erp.modules.workflow.infrastructure.effects import (
    WORKFLOW_INSTANCE_APPROVED,
    WORKFLOW_INSTANCE_REJECTED,
    WORKFLOW_STEP_APPROVED,
    WorkflowEffects,
)
from erp.modules.workflow.infrastructure.instances import PostgresWorkflowInstances
from erp.modules.workflow.infrastructure.repository import WorkflowRepository
from erp.modules.workflow.infrastructure.workflow_model import (
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)

__all__ = [
    "WORKFLOW_INSTANCE_APPROVED",
    "WORKFLOW_INSTANCE_REJECTED",
    "WORKFLOW_STEP_APPROVED",
    "ApprovalDecisionModel",
    "PostgresWorkflowApprovals",
    "PostgresWorkflowDecisions",
    "PostgresWorkflowDefinitions",
    "PostgresWorkflowInstances",
    "WorkflowDefinitionModel",
    "WorkflowEffects",
    "WorkflowInstanceModel",
    "WorkflowRepository",
    "WorkflowStepDefinitionModel",
    "WorkflowStepInstanceModel",
    "apply_workflow_decision",
]
