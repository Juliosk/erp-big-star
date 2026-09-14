"""Pure M22 workflow domain invariants."""

from uuid import uuid4

import pytest

from erp.modules.workflow.domain import (
    ApprovalDecision,
    ApprovalDecisionKind,
    ApprovalMode,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStepDefinition,
    WorkflowStepInstance,
)


def test_workflow_definition_normalizes_policy_and_steps() -> None:
    company_id = uuid4()

    definition = WorkflowDefinition.create(
        company_id=company_id,
        code=" quote-discount ",
        name=" Quote discount approval ",
        source_module="m15",
        source_type="sales_quote",
        approval_mode=ApprovalMode.SEQUENTIAL,
    )
    step = WorkflowStepDefinition.create(
        company_id=company_id,
        sequence=1,
        code=" manager ",
        name="Manager Approval",
        required_permission="sales.quote.approve.manager",
        threshold_amount="1000.00",
    )

    assert definition.code == "QUOTE-DISCOUNT"
    assert definition.source_module == "M15"
    assert definition.active is True
    assert definition.version == 1
    assert step.code == "MANAGER"
    assert step.threshold_amount is not None
    assert f"{step.threshold_amount:.2f}" == "1000.00"
    assert definition.deactivate().version == 2


def test_workflow_instance_and_step_transitions_are_strict() -> None:
    actor_id = uuid4()
    instance = WorkflowInstance.create(
        company_id=uuid4(),
        definition_id=uuid4(),
        source_module="M15",
        source_type="SALES_QUOTE",
        source_id=uuid4(),
        source_fingerprint="sha256:abc",
        requested_by=actor_id,
    )
    step = WorkflowStepInstance.create(
        company_id=instance.company_id,
        workflow_instance_id=instance.id,
        sequence=1,
        code="LEVEL-1",
        name="Level 1",
        required_permission="workflow.approval.decide",
        active=True,
    )

    approved = step.approve(actor_id=actor_id)
    final = instance.approve_final()

    assert instance.status == "PENDING"
    assert step.status == "ACTIVE"
    assert approved.status == "APPROVED"
    assert approved.decided_by == actor_id
    assert approved.version == 2
    assert final.status == "APPROVED"
    assert final.current_step_sequence is None
    with pytest.raises(ValueError, match="active"):
        approved.reject(actor_id=actor_id)


def test_approval_decision_keeps_decision_separate_from_business_effect() -> None:
    decision = ApprovalDecision.create(
        company_id=uuid4(),
        workflow_instance_id=uuid4(),
        step_instance_id=uuid4(),
        decision=ApprovalDecisionKind.REJECTED,
        decided_by=uuid4(),
        reason_code=" margin ",
        comment=" Margem abaixo da política ",
    )

    assert decision.decision == "REJECTED"
    assert decision.reason_code == "MARGIN"
    assert decision.comment == "Margem abaixo da política"
