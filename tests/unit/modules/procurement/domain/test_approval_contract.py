"""M6 approval handoff value objects remain independent from M22 internals."""

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.procurement.domain import (
    ApprovalLinked,
    ApprovalRequest,
    ApprovalSubjectType,
    ProcurementApprovalLinked,
    ProcurementApprovalRequested,
    ProcurementDomainError,
)


def approval_request() -> ApprovalRequest:
    return ApprovalRequest(
        company_id=uuid4(),
        subject_type=ApprovalSubjectType.PURCHASE_ORDER,
        subject_id=uuid4(),
        requested_by=uuid4(),
        amount=Decimal("100.125"),
        currency="brl",
        aggregate_version=2,
    )


def test_approval_request_is_normalized_and_has_stable_fingerprint() -> None:
    request = approval_request()
    assert request.amount == Decimal("100.13")
    assert request.currency == "BRL"
    assert request.fingerprint == (
        f"M6:PURCHASE_ORDER:{request.company_id}:{request.subject_id}:v2"
    )
    event = ProcurementApprovalRequested.from_request(request)
    assert event.request is request
    assert event.event_type == "ProcurementApprovalRequested"


def test_approval_link_and_event_are_framework_neutral() -> None:
    request = approval_request()
    link = ApprovalLinked(
        company_id=request.company_id,
        subject_type=request.subject_type,
        subject_id=request.subject_id,
        workflow_instance_id=uuid4(),
        aggregate_version=request.aggregate_version,
    )
    event = ProcurementApprovalLinked.from_link(link)
    assert event.link is link
    assert event.event_type == "ProcurementApprovalLinked"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_id", "bad"),
        ("subject_type", "bad"),
        ("subject_id", "bad"),
        ("requested_by", "bad"),
        ("amount", "bad"),
        ("currency", "REAL"),
        ("aggregate_version", 0),
        ("aggregate_version", True),
    ],
)
def test_approval_request_rejects_invalid_values(field: str, value: object) -> None:
    request = approval_request()
    with pytest.raises(ProcurementDomainError):
        replace(request, **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_id", "bad"),
        ("subject_type", "bad"),
        ("subject_id", "bad"),
        ("workflow_instance_id", "bad"),
        ("aggregate_version", 0),
    ],
)
def test_approval_link_rejects_invalid_values(field: str, value: object) -> None:
    request = approval_request()
    link = ApprovalLinked(
        company_id=request.company_id,
        subject_type=request.subject_type,
        subject_id=request.subject_id,
        workflow_instance_id=uuid4(),
        aggregate_version=2,
    )
    with pytest.raises(ProcurementDomainError):
        replace(link, **{field: value})  # type: ignore[arg-type]


def test_approval_events_require_valid_value_objects() -> None:
    with pytest.raises(ProcurementDomainError, match="ApprovalRequest"):
        ProcurementApprovalRequested.from_request("bad")  # type: ignore[arg-type]
    with pytest.raises(ProcurementDomainError, match="ApprovalLinked"):
        ProcurementApprovalLinked.from_link("bad")  # type: ignore[arg-type]
