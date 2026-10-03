"""Pure purchase order aggregate behavior and decimal invariants."""

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.procurement.domain import (
    ApprovalSubjectType,
    InvalidProcurementTransitionError,
    InvalidPurchaseOrderError,
    PaymentTerms,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
)


def payment_terms() -> PaymentTerms:
    return PaymentTerms.create(
        code=" 30-60 ", description=" Duas parcelas ", installment_days=(30, 60)
    )


def purchase_order(
    *, currencies: tuple[str, str] = ("BRL", "BRL"), duplicate: bool = False
) -> PurchaseOrder:
    requisition_item_a, requisition_item_b = uuid4(), uuid4()
    if duplicate:
        requisition_item_b = requisition_item_a
    return PurchaseOrder.create_from_requisition(
        company_id=uuid4(),
        number=" po-001 ",
        supplier_id=uuid4(),
        source_requisition_id=uuid4(),
        buyer_id=uuid4(),
        currency_code="brl",
        payment_terms=payment_terms(),
        lines=(
            (requisition_item_a, uuid4(), "2.500000", "10.125", currencies[0]),
            (requisition_item_b, uuid4(), 3, "7.50", currencies[1]),
        ),
    )


def test_payment_terms_and_purchase_order_totals_are_normalized() -> None:
    terms = payment_terms()
    order = purchase_order()
    assert terms.code == "30-60"
    assert terms.description == "Duas parcelas"
    assert order.number == "PO-001"
    assert order.currency == "BRL"
    assert order.status is PurchaseOrderStatus.DRAFT
    assert order.items[0].quantity == Decimal("2.500000")
    assert order.items[0].unit_price == Decimal("10.13")
    assert order.items[0].line_total == Decimal("25.33")
    assert order.total_amount == Decimal("47.83")
    assert all(item.purchase_order_id == order.id for item in order.items)


@pytest.mark.parametrize(
    "days",
    [(), (30, 30), (60, 30), (-1,), (True,)],
)
def test_payment_terms_reject_invalid_installments(days: tuple[int, ...]) -> None:
    with pytest.raises(InvalidPurchaseOrderError, match="installment_days"):
        PaymentTerms.create(code="NET", description="Valid", installment_days=days)


@pytest.mark.parametrize(("code", "description"), [("bad code", "Valid"), ("NET", " ")])
def test_payment_terms_reject_invalid_text(code: str, description: str) -> None:
    with pytest.raises(InvalidPurchaseOrderError):
        PaymentTerms.create(code=code, description=description, installment_days=(0,))


def test_purchase_order_approval_issue_and_approval_request() -> None:
    draft = purchase_order()
    pending = draft.submit_for_approval()
    request = pending.approval_request()
    assert pending.status is PurchaseOrderStatus.PENDING_APPROVAL
    assert request.subject_type is ApprovalSubjectType.PURCHASE_ORDER
    assert request.subject_id == draft.id
    assert request.requested_by == draft.buyer_id
    assert request.amount == draft.total_amount
    assert request.aggregate_version == 2
    approved = pending.approve()
    issued = approved.issue()
    assert issued.status is PurchaseOrderStatus.ISSUED
    assert issued.version == 4


def test_partial_and_complete_receipts_update_items_and_status() -> None:
    issued = purchase_order().submit_for_approval().approve().issue()
    first, second = issued.items
    partial = issued.receive(((first.id, "1.25"),))
    assert partial.status is PurchaseOrderStatus.PARTIALLY_RECEIVED
    assert partial.items[0].received_quantity == Decimal("1.250000")
    assert partial.items[0].outstanding_quantity == Decimal("1.250000")
    completed = partial.receive(
        (
            (first.id, "1.25"),
            (second.id, second.outstanding_quantity),
        )
    )
    assert completed.status is PurchaseOrderStatus.COMPLETED
    assert all(item.outstanding_quantity == 0 for item in completed.items)
    assert completed.total_amount == issued.total_amount


@pytest.mark.parametrize("receipts", [(), ((uuid4(), 1),), ((uuid4(), 1), (uuid4(), 1))])
def test_receipt_rejects_empty_unknown_or_wrong_state(
    receipts: tuple[tuple[object, object], ...],
) -> None:
    order = purchase_order()
    if not receipts:
        issued = order.submit_for_approval().approve().issue()
        with pytest.raises(InvalidPurchaseOrderError, match="unique"):
            issued.receive(())
        return
    with pytest.raises(InvalidProcurementTransitionError):
        order.receive(receipts)  # type: ignore[arg-type]
    issued = order.submit_for_approval().approve().issue()
    with pytest.raises(InvalidPurchaseOrderError, match="outside"):
        issued.receive(receipts)  # type: ignore[arg-type]


def test_receipt_rejects_duplicate_and_over_receipt() -> None:
    issued = purchase_order().submit_for_approval().approve().issue()
    item = issued.items[0]
    with pytest.raises(InvalidPurchaseOrderError, match="unique"):
        issued.receive(((item.id, 1), (item.id, 1)))
    with pytest.raises(InvalidPurchaseOrderError, match="exceed"):
        issued.receive(((item.id, item.quantity + 1),))
    with pytest.raises(InvalidPurchaseOrderError, match="positive"):
        item.receive(0)


@pytest.mark.parametrize(
    ("method", "status"),
    [
        ("submit_for_approval", PurchaseOrderStatus.APPROVED),
        ("approve", PurchaseOrderStatus.DRAFT),
        ("issue", PurchaseOrderStatus.PENDING_APPROVAL),
        ("approval_request", PurchaseOrderStatus.DRAFT),
    ],
)
def test_purchase_order_rejects_invalid_transitions(
    method: str, status: PurchaseOrderStatus
) -> None:
    with pytest.raises(InvalidProcurementTransitionError):
        getattr(replace(purchase_order(), status=status), method)()


@pytest.mark.parametrize(
    "status",
    [
        PurchaseOrderStatus.DRAFT,
        PurchaseOrderStatus.PENDING_APPROVAL,
        PurchaseOrderStatus.APPROVED,
        PurchaseOrderStatus.ISSUED,
    ],
)
def test_unreceived_purchase_order_can_be_cancelled(status: PurchaseOrderStatus) -> None:
    cancelled = replace(purchase_order(), status=status).cancel()
    assert cancelled.status is PurchaseOrderStatus.CANCELLED
    assert cancelled.version == 2


@pytest.mark.parametrize(
    "status", [PurchaseOrderStatus.PARTIALLY_RECEIVED, PurchaseOrderStatus.COMPLETED]
)
def test_received_or_terminal_purchase_order_cannot_be_cancelled(
    status: PurchaseOrderStatus,
) -> None:
    order = replace(purchase_order(), status=status)
    with pytest.raises(InvalidProcurementTransitionError):
        order.cancel()


def test_issued_order_with_any_received_quantity_cannot_be_cancelled() -> None:
    issued = purchase_order().submit_for_approval().approve().issue()
    received = issued.receive(((issued.items[0].id, 1),))
    with pytest.raises(InvalidProcurementTransitionError):
        replace(received, status=PurchaseOrderStatus.ISSUED).cancel()


def test_purchase_order_rejects_empty_duplicate_and_mixed_currency_lines() -> None:
    valid = purchase_order()
    with pytest.raises(InvalidPurchaseOrderError, match="at least one"):
        PurchaseOrder.create_from_requisition(
            company_id=valid.company_id,
            number="PO-EMPTY",
            supplier_id=valid.supplier_id,
            source_requisition_id=valid.source_requisition_id,
            buyer_id=valid.buyer_id,
            currency_code="BRL",
            payment_terms=valid.payment_terms,
            lines=(),
        )
    with pytest.raises(InvalidPurchaseOrderError, match="only once"):
        purchase_order(duplicate=True)
    with pytest.raises(InvalidPurchaseOrderError, match="order currency"):
        purchase_order(currencies=("BRL", "USD"))


def test_purchase_order_requires_valid_payment_terms() -> None:
    valid = purchase_order()
    with pytest.raises(InvalidPurchaseOrderError, match="PaymentTerms"):
        PurchaseOrder.create_from_requisition(
            company_id=valid.company_id,
            number="PO-NEW",
            supplier_id=valid.supplier_id,
            source_requisition_id=valid.source_requisition_id,
            buyer_id=valid.buyer_id,
            currency_code="BRL",
            payment_terms="NET30",  # type: ignore[arg-type]
            lines=((uuid4(), uuid4(), 1, 1, "BRL"),),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_id", "bad"),
        ("number", "bad number"),
        ("supplier_id", "bad"),
        ("source_requisition_id", "bad"),
        ("buyer_id", "bad"),
        ("currency_code", "REAL"),
    ],
)
def test_purchase_order_rejects_invalid_header(field: str, value: object) -> None:
    valid = purchase_order()
    values: dict[str, object] = {
        "company_id": valid.company_id,
        "number": "PO-NEW",
        "supplier_id": valid.supplier_id,
        "source_requisition_id": valid.source_requisition_id,
        "buyer_id": valid.buyer_id,
        "currency_code": "BRL",
        "payment_terms": valid.payment_terms,
        "lines": ((uuid4(), uuid4(), 1, 1, "BRL"),),
    }
    values[field] = value
    with pytest.raises(InvalidPurchaseOrderError):
        PurchaseOrder.create_from_requisition(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("requisition_item_id", "bad", "UUID"),
        ("product_id", "bad", "UUID"),
        ("quantity_value", 0, "positive"),
        ("unit_price", -1, "negative"),
        ("currency_code", "REAL", "ISO"),
    ],
)
def test_purchase_order_item_rejects_invalid_values(
    field: str, value: object, message: str
) -> None:
    values: dict[str, object] = {
        "company_id": uuid4(),
        "purchase_order_id": uuid4(),
        "requisition_item_id": uuid4(),
        "product_id": uuid4(),
        "quantity_value": 1,
        "unit_price": 1,
        "currency_code": "BRL",
    }
    values[field] = value
    with pytest.raises(InvalidPurchaseOrderError, match=message):
        PurchaseOrderItem.create(**values)  # type: ignore[arg-type]
