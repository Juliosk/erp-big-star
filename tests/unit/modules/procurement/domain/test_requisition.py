"""Pure purchase requisition aggregate behavior."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.procurement.domain import (
    ApprovalSubjectType,
    InvalidProcurementTransitionError,
    InvalidRequisitionError,
    PurchaseRequisition,
    RequisitionItem,
    RequisitionStatus,
    RequisitionUrgency,
)


def requisition(*, duplicate: bool = False) -> PurchaseRequisition:
    today = datetime.now(UTC).date()
    product_a, product_b = uuid4(), uuid4()
    if duplicate:
        product_b = product_a
    return PurchaseRequisition.create(
        company_id=uuid4(),
        number=" req-001 ",
        requester_id=uuid4(),
        cost_center_id=uuid4(),
        justification=" Reposicao de estoque ",
        lines=(
            (
                product_a,
                "2.5",
                "un",
                today + timedelta(days=10),
                RequisitionUrgency.NORMAL,
                "Produto conforme desenho A",
            ),
            (
                product_b,
                1,
                "cx",
                today + timedelta(days=3),
                RequisitionUrgency.CRITICAL,
                "Embalagem reforcada",
            ),
        ),
    )


def test_requisition_creation_normalizes_items_deadline_and_urgency() -> None:
    item = requisition()
    assert item.number == "REQ-001"
    assert item.justification == "Reposicao de estoque"
    assert item.status is RequisitionStatus.DRAFT
    assert item.version == 1
    assert item.items[0].quantity == Decimal("2.500000")
    assert item.items[0].unit_of_measure == "UN"
    assert item.deadline == datetime.now(UTC).date() + timedelta(days=3)
    assert item.urgency is RequisitionUrgency.CRITICAL
    assert all(line.requisition_id == item.id for line in item.items)
    assert all(line.company_id == item.company_id for line in item.items)


def test_requisition_lifecycle_and_approval_contract() -> None:
    draft = requisition()
    submitted = draft.submit()
    request = submitted.approval_request(estimated_amount="1234.567", currency="brl")
    assert submitted.status is RequisitionStatus.SUBMITTED
    assert submitted.version == 2
    assert request.subject_type is ApprovalSubjectType.PURCHASE_REQUISITION
    assert request.subject_id == draft.id
    assert request.requested_by == draft.requester_id
    assert request.amount == Decimal("1234.57")
    assert request.currency == "BRL"
    assert request.aggregate_version == 2
    assert submitted.approve().status is RequisitionStatus.APPROVED
    assert submitted.reject().status is RequisitionStatus.REJECTED


@pytest.mark.parametrize(
    "candidate",
    [
        lambda item: item.submit(),
        lambda item: item.approve(),
        lambda item: item.reject(),
        lambda item: item.approval_request(estimated_amount="1", currency="BRL"),
    ],
)
def test_requisition_rejects_transitions_from_wrong_state(candidate: object) -> None:
    with pytest.raises(InvalidProcurementTransitionError):
        candidate(replace(requisition(), status=RequisitionStatus.CANCELLED))  # type: ignore[operator]


@pytest.mark.parametrize(
    "status",
    [RequisitionStatus.DRAFT, RequisitionStatus.SUBMITTED, RequisitionStatus.APPROVED],
)
def test_active_requisition_can_be_cancelled(status: RequisitionStatus) -> None:
    cancelled = replace(requisition(), status=status).cancel()
    assert cancelled.status is RequisitionStatus.CANCELLED
    assert cancelled.version == 2


@pytest.mark.parametrize("status", [RequisitionStatus.REJECTED, RequisitionStatus.CANCELLED])
def test_terminal_requisition_cannot_be_cancelled(status: RequisitionStatus) -> None:
    with pytest.raises(InvalidProcurementTransitionError):
        replace(requisition(), status=status).cancel()


def test_requisition_rejects_empty_and_duplicate_lines() -> None:
    source = requisition()
    with pytest.raises(InvalidRequisitionError, match="at least one"):
        PurchaseRequisition.create(
            company_id=source.company_id,
            number="REQ-EMPTY",
            requester_id=source.requester_id,
            cost_center_id=source.cost_center_id,
            justification="Required",
            lines=(),
        )
    with pytest.raises(InvalidRequisitionError, match="only once"):
        requisition(duplicate=True)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("needed_by", "tomorrow", "date"),
        ("needed_by", datetime.now(UTC).date() - timedelta(days=1), "past"),
        ("urgency", "NOW", "urgency"),
        ("quantity_value", 0, "positive"),
        ("unit_of_measure", "bad value", "identifier"),
        ("specification", " ", "specification"),
        ("product_id", "bad", "UUID"),
    ],
)
def test_requisition_item_rejects_invalid_values(field: str, value: object, message: str) -> None:
    values: dict[str, object] = {
        "company_id": uuid4(),
        "requisition_id": uuid4(),
        "product_id": uuid4(),
        "quantity_value": 1,
        "unit_of_measure": "UN",
        "needed_by": datetime.now(UTC).date() + timedelta(days=1),
        "urgency": RequisitionUrgency.NORMAL,
        "specification": "Valid item",
    }
    values[field] = value
    with pytest.raises(InvalidRequisitionError, match=message):
        RequisitionItem.create(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_id", "bad"),
        ("number", "bad number"),
        ("requester_id", "bad"),
        ("cost_center_id", "bad"),
        ("justification", " "),
    ],
)
def test_requisition_rejects_invalid_header_values(field: str, value: object) -> None:
    valid = requisition()
    values: dict[str, object] = {
        "company_id": valid.company_id,
        "number": "REQ-NEW",
        "requester_id": valid.requester_id,
        "cost_center_id": valid.cost_center_id,
        "justification": "Valid",
        "lines": (
            (
                uuid4(),
                1,
                "UN",
                datetime.now(UTC).date() + timedelta(days=1),
                RequisitionUrgency.LOW,
                "Valid",
            ),
        ),
    }
    values[field] = value
    with pytest.raises(InvalidRequisitionError):
        PurchaseRequisition.create(**values)  # type: ignore[arg-type]
