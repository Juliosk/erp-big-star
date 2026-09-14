"""Pure domain model for M22 Workflow."""

from erp.modules.workflow.domain.approval import (
    ApprovalDecision,
    ApprovalDecisionKind,
)
from erp.modules.workflow.domain.definition import (
    ApprovalMode,
    WorkflowDefinition,
    WorkflowStepDefinition,
)
from erp.modules.workflow.domain.instance import (
    WorkflowInstance,
    WorkflowInstanceStatus,
    WorkflowStepInstance,
    WorkflowStepStatus,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalDecisionKind",
    "ApprovalMode",
    "WorkflowDefinition",
    "WorkflowInstance",
    "WorkflowInstanceStatus",
    "WorkflowStepDefinition",
    "WorkflowStepInstance",
    "WorkflowStepStatus",
]
