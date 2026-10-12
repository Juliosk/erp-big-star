"""Pure payable governance rules."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.domain import (
    InvalidPayableError,
    InvalidPayableStateError,
    PayableApprovalStatus,
    PayableDivergenceBlockedError,
    PayableGovernance,
)


def governance() -> PayableGovernance:
    return PayableGovernance(company_id=uuid4(), payable_id=uuid4())


def test_divergence_gate_blocks_and_can_be_cleared() -> None:
    original = governance()
    blocked = original.apply_divergence(fiscal_blocked=True, purchasing_blocked=False)
    assert blocked.blocked is True
    with pytest.raises(PayableDivergenceBlockedError):
        blocked.require_unblocked()
    cleared = blocked.apply_divergence(fiscal_blocked=False, purchasing_blocked=False)
    cleared.require_unblocked()
    assert cleared.blocked is False
    assert cleared.version == 3


def test_workflow_request_and_matching_decision() -> None:
    workflow_id = uuid4()
    requested = governance().request_approval(
        workflow_instance_id=workflow_id,
        authority_limit=Decimal("100.00"),
        sod_threshold=Decimal("50.00"),
    )
    assert requested.approval_status is PayableApprovalStatus.PENDING
    approved = requested.decide(approved=True, workflow_instance_id=workflow_id)
    assert approved.approval_status is PayableApprovalStatus.APPROVED


def test_direct_authority_marks_governance_approved() -> None:
    approved = governance().request_approval(
        workflow_instance_id=None,
        authority_limit=None,
        sod_threshold=Decimal("100.00"),
    )
    assert approved.approval_status is PayableApprovalStatus.APPROVED


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"company_id": UUID(int=0)}, "company_id"),
        ({"payable_id": UUID(int=0)}, "payable_id"),
        ({"approval_status": "PENDING"}, "approval_status"),
        ({"workflow_instance_id": "bad"}, "workflow_instance_id"),
        ({"authority_limit": Decimal("1.001")}, "authority_limit"),
        ({"sod_threshold": Decimal("-1.00")}, "sod_threshold"),
        ({"version": 0}, "version"),
    ],
)
def test_invalid_governance_is_rejected(changes: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "company_id": uuid4(),
        "payable_id": uuid4(),
    }
    values.update(changes)
    with pytest.raises(InvalidPayableError, match=message):
        PayableGovernance(**values)  # type: ignore[arg-type]


def test_duplicate_request_and_wrong_workflow_decision_are_rejected() -> None:
    workflow_id = uuid4()
    requested = governance().request_approval(
        workflow_instance_id=workflow_id,
        authority_limit=Decimal("10.00"),
        sod_threshold=Decimal("1.00"),
    )
    with pytest.raises(InvalidPayableStateError, match="already requested"):
        requested.request_approval(
            workflow_instance_id=workflow_id,
            authority_limit=Decimal("10.00"),
            sod_threshold=Decimal("1.00"),
        )
    with pytest.raises(InvalidPayableError, match="does not match"):
        requested.decide(approved=False, workflow_instance_id=uuid4())
    with pytest.raises(InvalidPayableStateError, match="not pending"):
        governance().decide(approved=True, workflow_instance_id=workflow_id)
