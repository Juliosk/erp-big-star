"""Application services and policies for M22 Workflow."""

from erp.modules.workflow.application.definitions import (
    CreateWorkflowDefinition,
    CreateWorkflowStepDefinition,
    DeactivateWorkflowDefinition,
    WorkflowDefinitionDetail,
    WorkflowDefinitionService,
    WorkflowDefinitionStore,
    WorkflowPage,
)
from erp.modules.workflow.application.instances import (
    OpenWorkflowInstance,
    WorkflowInstanceDetail,
    WorkflowInstanceService,
    WorkflowInstanceStore,
)
from erp.modules.workflow.application.permissions import (
    WORKFLOW_APPROVAL_DECIDE,
    WORKFLOW_DEFINITION_MANAGE,
    WORKFLOW_REQUEST_CREATE,
    WORKFLOW_REQUEST_READ,
    WorkflowAuthorization,
    workflow_permission_registry,
)

__all__ = [
    "WORKFLOW_APPROVAL_DECIDE",
    "WORKFLOW_DEFINITION_MANAGE",
    "WORKFLOW_REQUEST_CREATE",
    "WORKFLOW_REQUEST_READ",
    "CreateWorkflowDefinition",
    "CreateWorkflowStepDefinition",
    "DeactivateWorkflowDefinition",
    "OpenWorkflowInstance",
    "WorkflowAuthorization",
    "WorkflowDefinitionDetail",
    "WorkflowDefinitionService",
    "WorkflowDefinitionStore",
    "WorkflowInstanceDetail",
    "WorkflowInstanceService",
    "WorkflowInstanceStore",
    "WorkflowPage",
    "workflow_permission_registry",
]
