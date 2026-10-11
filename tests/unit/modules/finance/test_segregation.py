"""Pure high-value accounts-payable segregation rules."""

from dataclasses import FrozenInstanceError
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.domain import (
    InvalidSegregationPolicyError,
    PayableSegregationPolicy,
    SegregationOfDutiesViolation,
)


def test_high_value_provision_requires_another_approver() -> None:
    actor_id = uuid4()
    policy = PayableSegregationPolicy(Decimal("10000.00"))

    with pytest.raises(SegregationOfDutiesViolation) as captured:
        policy.require_distinct_approver(
            created_by=actor_id,
            approver_id=actor_id,
            amount=Decimal("10000.00"),
        )

    assert captured.value.code == "SOD_VIOLATION"


def test_low_value_self_approval_and_distinct_high_value_approval_are_allowed() -> None:
    actor_id = uuid4()
    policy = PayableSegregationPolicy(Decimal("10000.00"))

    policy.require_distinct_approver(
        created_by=actor_id,
        approver_id=actor_id,
        amount=Decimal("9999.99"),
    )
    policy.require_distinct_approver(
        created_by=actor_id,
        approver_id=uuid4(),
        amount=Decimal("10000.00"),
    )


def test_segregation_policy_is_immutable_and_validates_inputs() -> None:
    policy = PayableSegregationPolicy(Decimal("10.00"))
    with pytest.raises(FrozenInstanceError):
        policy.high_value_threshold = Decimal("20.00")  # type: ignore[misc]

    for invalid in (Decimal("0"), Decimal("-1"), Decimal("1.001"), Decimal("NaN")):
        with pytest.raises(InvalidSegregationPolicyError):
            PayableSegregationPolicy(invalid)
    with pytest.raises(InvalidSegregationPolicyError, match="supported monetary precision"):
        PayableSegregationPolicy(Decimal("12345678901234567890123456789"))

    with pytest.raises(InvalidSegregationPolicyError):
        PayableSegregationPolicy(Decimal("10.00")).require_distinct_approver(
            created_by=UUID(int=0),
            approver_id=uuid4(),
            amount=Decimal("1.00"),
        )
    with pytest.raises(InvalidSegregationPolicyError):
        PayableSegregationPolicy(Decimal("10.00")).require_distinct_approver(
            created_by=uuid4(),
            approver_id=UUID(int=0),
            amount=Decimal("1.00"),
        )
    with pytest.raises(InvalidSegregationPolicyError):
        PayableSegregationPolicy(Decimal("10.00")).require_distinct_approver(
            created_by=uuid4(),
            approver_id=uuid4(),
            amount=Decimal("1.001"),
        )
    with pytest.raises(InvalidSegregationPolicyError, match="finite Decimal"):
        PayableSegregationPolicy(Decimal("10.00")).require_distinct_approver(
            created_by=uuid4(),
            approver_id=uuid4(),
            amount=Decimal("Infinity"),
        )
