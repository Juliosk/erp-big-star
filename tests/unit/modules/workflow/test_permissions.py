"""M22 Workflow permission registry."""

from erp.modules.workflow.application import (
    WORKFLOW_APPROVAL_DECIDE,
    WORKFLOW_DEFINITION_MANAGE,
    WORKFLOW_REQUEST_CREATE,
    WORKFLOW_REQUEST_READ,
    workflow_permission_registry,
)


def test_workflow_permissions_are_explicit_and_high_risk_decisions() -> None:
    registry = workflow_permission_registry()

    assert registry.get(WORKFLOW_REQUEST_READ) is not None
    assert registry.get(WORKFLOW_REQUEST_CREATE) is not None
    assert registry.get(WORKFLOW_APPROVAL_DECIDE) is not None
    assert registry.get(WORKFLOW_DEFINITION_MANAGE) is not None
    assert registry.get(WORKFLOW_APPROVAL_DECIDE).risk_level == "CRITICAL"
    assert registry.get(WORKFLOW_DEFINITION_MANAGE).data_classification == "RESTRICTED"
