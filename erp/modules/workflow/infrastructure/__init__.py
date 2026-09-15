"""Internal M22 persistence adapters, wired only at the composition boundary."""

from erp.modules.workflow.infrastructure.definitions import PostgresWorkflowDefinitions
from erp.modules.workflow.infrastructure.repository import WorkflowRepository
from erp.modules.workflow.infrastructure.workflow_model import (
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)

__all__ = [
    "ApprovalDecisionModel",
    "PostgresWorkflowDefinitions",
    "WorkflowDefinitionModel",
    "WorkflowInstanceModel",
    "WorkflowRepository",
    "WorkflowStepDefinitionModel",
    "WorkflowStepInstanceModel",
]
