"""Pure M6 GoodsReceipt invariants and M17/M5 contracts."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.procurement.domain import (
    GoodsReceipt,
    GoodsReceiptStatus,
    InspectionDisposition,
    InvalidGoodsReceiptError,
    InvalidProcurementTransitionError,
    InventoryPostingConfirmation,
    InventoryReceiptState,
    PaymentTerms,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    QualityInspectionResult,
    ReceiptItem,
    ReceiptQuantityVariance,
    ReceiptTolerance,
)


def issued_order() -> PurchaseOrder:
    order = PurchaseOrder.create_from_requisition(
        company_id=uuid4(),
        number="PO-RECEIPT-001",
        supplier_id=uuid4(),
        source_requisition_id=uuid4(),
        buyer_id=uuid4(),
        currency_code="BRL",
        payment_terms=PaymentTerms.create(
            code="30D", description="Trinta dias", installment_days=(30,)
        ),
        lines=(
            (uuid4(), uuid4(), "10", "12.50", "BRL"),
            (uuid4(), uuid4(), "4", "7.25", "BRL"),
        ),
    )
    return order.submit_for_approval().approve().issue()


def receipt(
    *,
    order: PurchaseOrder | None = None,
    first_quantity: str = "10",
    second_quantity: str = "4",
    first_conforms: bool = True,
    first_note: str | None = None,
    tolerance: str = "0",
) -> GoodsReceipt:
    source = order or issued_order()
    return GoodsReceipt.create_from_purchase_order(
        company_id=source.company_id,
        number="GR-0001",
        purchase_order=source,
        warehouse_id=uuid4(),
        received_by=uuid4(),
        tolerance=ReceiptTolerance.create(tolerance),
        lines=(
            (
                source.items[0].id,
                first_quantity,
                first_conforms,
                first_note,
                "lot-001",
            ),
            (source.items[1].id, second_quantity, True, None, None),
        ),
    )


def inspected_receipt(*, partial: bool = False) -> GoodsReceipt:
    received = receipt().confirm_received()
    first, second = received.items
    first_result = (
        QualityInspectionResult.create(
            item=first,
            inspection_id=uuid4(),
            disposition=InspectionDisposition.PARTIAL_ACCEPTANCE,
            approved_quantity="7",
            quarantine_quantity="3",
            reason_code="QUALITY-HOLD",
        )
        if partial
        else approved_result(first)
    )
    return received.apply_inspection_results((first_result, approved_result(second)))


def approved_result(item: ReceiptItem) -> QualityInspectionResult:
    return QualityInspectionResult.create(
        item=item,
        inspection_id=uuid4(),
        disposition=InspectionDisposition.APPROVE,
        approved_quantity=item.received_quantity,
    )


def test_receipt_tracks_order_snapshot_and_quantity_divergences() -> None:
    created = receipt(first_quantity="8", first_conforms=False, first_note="Caixa divergente")
    first, second = created.items
    assert created.status is GoodsReceiptStatus.DRAFT
    assert created.version == 1
    assert first.quantity_variance == Decimal("-2.000000")
    assert first.quantity_variance_kind is ReceiptQuantityVariance.SHORT
    assert first.has_divergence
    assert second.quantity_variance_kind is ReceiptQuantityVariance.EXACT
    assert not second.has_divergence
    assert first.lot_reference == "LOT-001"

    confirmed = created.confirm_received(occurred_at=datetime(2026, 10, 4, 10, 30, tzinfo=UTC))
    requests = confirmed.inspection_requests()
    assert confirmed.status is GoodsReceiptStatus.RECEIVED
    assert confirmed.version == 2
    assert requests[0].purchase_order_id == created.purchase_order_id
    assert requests[0].has_quantity_divergence
    assert requests[0].has_specification_divergence
    assert requests[0].quantity == Decimal("8.000000")


def test_over_receipt_uses_percentage_of_original_order_quantity() -> None:
    accepted = receipt(first_quantity="10.5", tolerance="5")
    assert accepted.items[0].quantity_variance_kind is ReceiptQuantityVariance.OVER
    assert accepted.items[0].quantity_variance == Decimal("0.500000")
    with pytest.raises(InvalidGoodsReceiptError, match="exceeds"):
        receipt(first_quantity="10.500001", tolerance="5")


@pytest.mark.parametrize("value", ["-0.1", "100.0001", "NaN", "bad"])
def test_tolerance_rejects_invalid_percentages(value: str) -> None:
    with pytest.raises(InvalidGoodsReceiptError):
        ReceiptTolerance.create(value)


def test_quality_approval_builds_pure_inventory_contract_and_posts() -> None:
    inspected = inspected_receipt()
    assert inspected.status is GoodsReceiptStatus.INSPECTED
    assert inspected.version == 3
    assert len(inspected.posting_requests) == 2
    assert all(
        request.state is InventoryReceiptState.AVAILABLE for request in inspected.posting_requests
    )
    assert {request.warehouse_id for request in inspected.posting_requests} == {
        inspected.warehouse_id
    }
    confirmations = tuple(
        InventoryPostingConfirmation.create(
            posting_request_id=request.id, inventory_transaction_id=uuid4()
        )
        for request in inspected.posting_requests
    )
    posted = inspected.confirm_inventory_posting(confirmations)
    assert posted.status is GoodsReceiptStatus.POSTED
    assert posted.version == 4
    assert len(posted.inventory_transaction_ids) == 2


def test_partial_acceptance_splits_available_and_quarantine_postings() -> None:
    inspected = inspected_receipt(partial=True)
    first_requests = [
        request
        for request in inspected.posting_requests
        if request.receipt_item_id == inspected.items[0].id
    ]
    assert [(request.state, request.quantity) for request in first_requests] == [
        (InventoryReceiptState.AVAILABLE, Decimal("7.000000")),
        (InventoryReceiptState.QUARANTINE, Decimal("3.000000")),
    ]


def test_complete_quality_rejection_is_terminal_rejected() -> None:
    received = receipt().confirm_received()
    results = tuple(
        QualityInspectionResult.create(
            item=item,
            inspection_id=uuid4(),
            disposition=InspectionDisposition.REJECT,
            rejected_quantity=item.received_quantity,
            reason_code="SPEC-REJECTED",
        )
        for item in received.items
    )
    rejected = received.apply_inspection_results(results)
    assert rejected.status is GoodsReceiptStatus.REJECTED
    assert rejected.posting_requests == ()
    with pytest.raises(InvalidProcurementTransitionError):
        rejected.confirm_inventory_posting(())


@pytest.mark.parametrize(
    ("disposition", "approved", "rejected", "quarantine", "reason"),
    [
        (InspectionDisposition.APPROVE, "9", "1", "0", None),
        (InspectionDisposition.REJECT, "0", "9", "1", "REJECTED"),
        (InspectionDisposition.QUARANTINE, "0", "1", "9", "HOLD"),
        (InspectionDisposition.PARTIAL_ACCEPTANCE, "10", "0", "0", "PARTIAL"),
        (InspectionDisposition.PARTIAL_ACCEPTANCE, "0", "10", "0", "PARTIAL"),
        (InspectionDisposition.REJECT, "0", "10", "0", None),
    ],
)
def test_quality_result_rejects_inconsistent_disposition(
    disposition: InspectionDisposition,
    approved: str,
    rejected: str,
    quarantine: str,
    reason: str | None,
) -> None:
    item = receipt().items[0]
    with pytest.raises(InvalidGoodsReceiptError):
        QualityInspectionResult.create(
            item=item,
            inspection_id=uuid4(),
            disposition=disposition,
            approved_quantity=approved,
            rejected_quantity=rejected,
            quarantine_quantity=quarantine,
            reason_code=reason,
        )


def test_quality_result_rejects_negative_or_unbalanced_quantities() -> None:
    item = receipt().items[0]
    with pytest.raises(InvalidGoodsReceiptError, match="negative"):
        QualityInspectionResult.create(
            item=item,
            inspection_id=uuid4(),
            disposition=InspectionDisposition.PARTIAL_ACCEPTANCE,
            approved_quantity="11",
            rejected_quantity="-1",
            reason_code="INVALID",
        )
    with pytest.raises(InvalidGoodsReceiptError, match="equal"):
        QualityInspectionResult.create(
            item=item,
            inspection_id=uuid4(),
            disposition=InspectionDisposition.APPROVE,
            approved_quantity="9",
        )


def test_receipt_rejects_wrong_order_state_scope_and_lines() -> None:
    source = issued_order()
    warehouse_id, received_by = uuid4(), uuid4()
    lines = ((source.items[0].id, "1", True, None, None),)
    with pytest.raises(InvalidGoodsReceiptError, match="issued"):
        GoodsReceipt.create_from_purchase_order(
            company_id=source.company_id,
            number="GR-INVALID",
            purchase_order=replace(source, status=PurchaseOrderStatus.APPROVED),
            warehouse_id=warehouse_id,
            received_by=received_by,
            tolerance=ReceiptTolerance.create(),
            lines=lines,
        )
    with pytest.raises(InvalidGoodsReceiptError, match="outside the receipt company"):
        GoodsReceipt.create_from_purchase_order(
            company_id=uuid4(),
            number="GR-INVALID",
            purchase_order=source,
            warehouse_id=warehouse_id,
            received_by=received_by,
            tolerance=ReceiptTolerance.create(),
            lines=lines,
        )
    with pytest.raises(InvalidGoodsReceiptError, match="unique"):
        GoodsReceipt.create_from_purchase_order(
            company_id=source.company_id,
            number="GR-INVALID",
            purchase_order=source,
            warehouse_id=warehouse_id,
            received_by=received_by,
            tolerance=ReceiptTolerance.create(),
            lines=(),
        )
    with pytest.raises(InvalidGoodsReceiptError, match="outside the purchase order"):
        GoodsReceipt.create_from_purchase_order(
            company_id=source.company_id,
            number="GR-INVALID",
            purchase_order=source,
            warehouse_id=warehouse_id,
            received_by=received_by,
            tolerance=ReceiptTolerance.create(),
            lines=((uuid4(), "1", True, None, None),),
        )


def test_receipt_item_requires_discrepancy_reason_and_open_order_quantity() -> None:
    with pytest.raises(InvalidGoodsReceiptError, match="discrepancy_note"):
        receipt(first_conforms=False)
    source = issued_order()
    completed_item = replace(source.items[0], received_quantity=source.items[0].quantity)
    source = replace(source, items=(completed_item, source.items[1]))
    with pytest.raises(InvalidGoodsReceiptError, match="no outstanding"):
        receipt(order=source)


def test_receipt_item_rejects_invalid_boundary_contracts() -> None:
    source = issued_order()
    item = source.items[0]
    receipt_id = uuid4()
    tolerance = ReceiptTolerance.create()

    def create_item(
        order_item: PurchaseOrderItem,
        *,
        received_quantity: str = "1",
        item_tolerance: ReceiptTolerance = tolerance,
        specification_conforms: bool = True,
    ) -> ReceiptItem:
        return ReceiptItem.create(
            company_id=source.company_id,
            goods_receipt_id=receipt_id,
            order_item=order_item,
            received_quantity=received_quantity,
            tolerance=item_tolerance,
            specification_conforms=specification_conforms,
        )

    with pytest.raises(InvalidGoodsReceiptError, match="purchase order item"):
        create_item(cast(PurchaseOrderItem, "invalid"))
    with pytest.raises(InvalidGoodsReceiptError, match="outside the receipt company"):
        create_item(replace(item, company_id=uuid4()))
    with pytest.raises(InvalidGoodsReceiptError, match="ReceiptTolerance"):
        create_item(item, item_tolerance=cast(ReceiptTolerance, "invalid"))
    with pytest.raises(InvalidGoodsReceiptError, match="boolean"):
        create_item(item, specification_conforms=cast(bool, 1))
    with pytest.raises(InvalidGoodsReceiptError, match="valid decimal"):
        create_item(item, received_quantity="invalid")


def test_m17_and_m5_value_contracts_reject_invalid_boundary_values() -> None:
    item = receipt().items[0]
    with pytest.raises(InvalidGoodsReceiptError, match="receipt item"):
        QualityInspectionResult.create(
            item=cast(ReceiptItem, "invalid"),
            inspection_id=uuid4(),
            disposition=InspectionDisposition.APPROVE,
        )
    with pytest.raises(InvalidGoodsReceiptError, match="M17 decision"):
        QualityInspectionResult.create(
            item=item,
            inspection_id=uuid4(),
            disposition=cast(InspectionDisposition, "invalid"),
            approved_quantity=item.received_quantity,
        )
    with pytest.raises(InvalidGoodsReceiptError, match="reason_code"):
        QualityInspectionResult.create(
            item=item,
            inspection_id=uuid4(),
            disposition=InspectionDisposition.REJECT,
            rejected_quantity=item.received_quantity,
            reason_code="invalid reason",
        )
    with pytest.raises(InvalidGoodsReceiptError, match="inspection_id"):
        QualityInspectionResult.create(
            item=item,
            inspection_id=cast(UUID, "invalid"),
            disposition=InspectionDisposition.APPROVE,
            approved_quantity=item.received_quantity,
        )
    with pytest.raises(InvalidGoodsReceiptError, match="posting_request_id"):
        InventoryPostingConfirmation.create(
            posting_request_id=cast(UUID, "invalid"),
            inventory_transaction_id=uuid4(),
        )


def test_receipt_header_rejects_invalid_boundary_contracts() -> None:
    source = issued_order()
    warehouse_id, received_by = uuid4(), uuid4()
    tolerance = ReceiptTolerance.create()
    lines = ((source.items[0].id, "1", True, None, None),)

    def create_receipt(
        purchase_order: PurchaseOrder,
        *,
        number: str = "GR-INVALID",
        receipt_tolerance: ReceiptTolerance = tolerance,
    ) -> GoodsReceipt:
        return GoodsReceipt.create_from_purchase_order(
            company_id=source.company_id,
            number=number,
            purchase_order=purchase_order,
            warehouse_id=warehouse_id,
            received_by=received_by,
            tolerance=receipt_tolerance,
            lines=lines,
        )

    with pytest.raises(InvalidGoodsReceiptError, match="PurchaseOrder"):
        create_receipt(cast(PurchaseOrder, "invalid"))
    with pytest.raises(InvalidGoodsReceiptError, match="ReceiptTolerance"):
        create_receipt(source, receipt_tolerance=cast(ReceiptTolerance, "invalid"))
    with pytest.raises(InvalidGoodsReceiptError, match="number"):
        create_receipt(source, number="invalid number")


def test_inspection_rejects_wrong_state_and_cross_scope_result() -> None:
    draft = receipt()
    with pytest.raises(InvalidProcurementTransitionError):
        draft.apply_inspection_results(())

    received = draft.confirm_received()
    results = tuple(approved_result(item) for item in received.items)
    foreign_result = replace(results[0], company_id=uuid4())
    with pytest.raises(InvalidGoodsReceiptError, match="outside the receipt scope"):
        received.apply_inspection_results((foreign_result, results[1]))


def test_mixed_rejection_routes_rejected_quantity_to_quarantine() -> None:
    received = receipt().confirm_received()
    first, second = received.items
    rejected = QualityInspectionResult.create(
        item=first,
        inspection_id=uuid4(),
        disposition=InspectionDisposition.REJECT,
        rejected_quantity=first.received_quantity,
        reason_code="SPEC-REJECTED",
    )
    inspected = received.apply_inspection_results((rejected, approved_result(second)))
    first_requests = [
        request for request in inspected.posting_requests if request.receipt_item_id == first.id
    ]
    assert inspected.status is GoodsReceiptStatus.INSPECTED
    assert [(request.state, request.quantity) for request in first_requests] == [
        (InventoryReceiptState.QUARANTINE, first.received_quantity)
    ]


def test_inspection_and_posting_require_complete_exact_contracts() -> None:
    draft = receipt()
    with pytest.raises(InvalidProcurementTransitionError):
        draft.inspection_requests()
    with pytest.raises(InvalidGoodsReceiptError, match="timezone-aware"):
        draft.confirm_received(
            occurred_at=datetime(2026, 10, 4, 10, 0, tzinfo=UTC).replace(tzinfo=None)
        )
    received = draft.confirm_received()
    with pytest.raises(InvalidProcurementTransitionError):
        received.confirm_received()
    with pytest.raises(InvalidGoodsReceiptError, match="every receipt item"):
        received.apply_inspection_results((approved_result(received.items[0]),))

    inspected = inspected_receipt()
    with pytest.raises(InvalidGoodsReceiptError, match="every posting request"):
        inspected.confirm_inventory_posting(())
    duplicate_transaction = uuid4()
    confirmations = tuple(
        InventoryPostingConfirmation.create(
            posting_request_id=request.id,
            inventory_transaction_id=duplicate_transaction,
        )
        for request in inspected.posting_requests
    )
    with pytest.raises(InvalidGoodsReceiptError, match="unique"):
        inspected.confirm_inventory_posting(confirmations)
