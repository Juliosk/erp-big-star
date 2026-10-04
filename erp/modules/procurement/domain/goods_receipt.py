"""Pure M6 physical receipt aggregate and public M17/M5 value contracts."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.procurement.domain.exceptions import (
    InvalidGoodsReceiptError,
    InvalidProcurementTransitionError,
    ProcurementDomainError,
)
from erp.modules.procurement.domain.purchase_order import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
)
from erp.modules.procurement.domain.support import identifier, quantity, require_uuid, text

_QUANTITY_QUANTUM = Decimal("0.000001")
_PERCENTAGE_QUANTUM = Decimal("0.0001")


class GoodsReceiptStatus(StrEnum):
    DRAFT = "DRAFT"
    RECEIVED = "RECEIVED"
    INSPECTED = "INSPECTED"
    POSTED = "POSTED"
    REJECTED = "REJECTED"


class ReceiptQuantityVariance(StrEnum):
    SHORT = "SHORT"
    EXACT = "EXACT"
    OVER = "OVER"


class InspectionDisposition(StrEnum):
    APPROVE = "APPROVE"
    PARTIAL_ACCEPTANCE = "PARTIAL_ACCEPTANCE"
    REJECT = "REJECT"
    QUARANTINE = "QUARANTINE"


class InventoryReceiptState(StrEnum):
    AVAILABLE = "AVAILABLE"
    QUARANTINE = "QUARANTINE"


@dataclass(frozen=True, slots=True)
class ReceiptTolerance:
    """Maximum extra quantity accepted over the original ordered quantity."""

    max_overage_percentage: Decimal

    @classmethod
    def create(cls, max_overage_percentage: Decimal | str | int = 0) -> ReceiptTolerance:
        value = _decimal(max_overage_percentage, "max_overage_percentage", _PERCENTAGE_QUANTUM)
        if value < 0 or value > 100:
            raise InvalidGoodsReceiptError("max_overage_percentage must be between 0 and 100.")
        return cls(value)

    def allowed_overage(self, ordered_quantity: Decimal) -> Decimal:
        return (ordered_quantity * self.max_overage_percentage / 100).quantize(
            _QUANTITY_QUANTUM, rounding=ROUND_HALF_UP
        )


@dataclass(frozen=True, slots=True)
class ReceiptItem:
    id: UUID
    company_id: UUID
    goods_receipt_id: UUID
    purchase_order_item_id: UUID
    product_id: UUID
    ordered_quantity: Decimal
    previously_received_quantity: Decimal
    expected_quantity: Decimal
    received_quantity: Decimal
    tolerance: ReceiptTolerance
    specification_conforms: bool
    discrepancy_note: str | None
    lot_reference: str | None

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        goods_receipt_id: UUID,
        order_item: PurchaseOrderItem,
        received_quantity: Decimal | str | int,
        tolerance: ReceiptTolerance,
        specification_conforms: bool,
        discrepancy_note: str | None = None,
        lot_reference: str | None = None,
    ) -> ReceiptItem:
        if not isinstance(order_item, PurchaseOrderItem):
            raise InvalidGoodsReceiptError("order_item must be a purchase order item.")
        if order_item.company_id != company_id:
            raise InvalidGoodsReceiptError("order item is outside the receipt company.")
        if not isinstance(tolerance, ReceiptTolerance):
            raise InvalidGoodsReceiptError("tolerance must be a ReceiptTolerance.")
        if type(specification_conforms) is not bool:
            raise InvalidGoodsReceiptError("specification_conforms must be boolean.")
        if order_item.outstanding_quantity <= 0:
            raise InvalidGoodsReceiptError("purchase order item has no outstanding quantity.")
        try:
            received = quantity(received_quantity)
            note = (
                None
                if discrepancy_note is None
                else text(discrepancy_note, "discrepancy_note", maximum=1000)
            )
            lot = (
                None
                if lot_reference is None
                else identifier(lot_reference, "lot_reference", maximum=64)
            )
            if not specification_conforms and note is None:
                raise InvalidGoodsReceiptError(
                    "a specification discrepancy requires a discrepancy_note."
                )
            maximum = order_item.outstanding_quantity + tolerance.allowed_overage(
                order_item.quantity
            )
            if received > maximum:
                raise InvalidGoodsReceiptError(
                    "received quantity exceeds outstanding quantity plus tolerance."
                )
            return cls(
                id=uuid4(),
                company_id=require_uuid(company_id, "company_id"),
                goods_receipt_id=require_uuid(goods_receipt_id, "goods_receipt_id"),
                purchase_order_item_id=order_item.id,
                product_id=order_item.product_id,
                ordered_quantity=order_item.quantity,
                previously_received_quantity=order_item.received_quantity,
                expected_quantity=order_item.outstanding_quantity,
                received_quantity=received,
                tolerance=tolerance,
                specification_conforms=specification_conforms,
                discrepancy_note=note,
                lot_reference=lot,
            )
        except ProcurementDomainError as error:
            if isinstance(error, InvalidGoodsReceiptError):
                raise
            raise InvalidGoodsReceiptError(str(error)) from error

    @property
    def quantity_variance(self) -> Decimal:
        return self.received_quantity - self.expected_quantity

    @property
    def quantity_variance_kind(self) -> ReceiptQuantityVariance:
        if self.quantity_variance < 0:
            return ReceiptQuantityVariance.SHORT
        if self.quantity_variance > 0:
            return ReceiptQuantityVariance.OVER
        return ReceiptQuantityVariance.EXACT

    @property
    def has_divergence(self) -> bool:
        return self.quantity_variance != 0 or not self.specification_conforms


@dataclass(frozen=True, slots=True)
class IncomingInspectionRequest:
    company_id: UUID
    goods_receipt_id: UUID
    receipt_item_id: UUID
    purchase_order_id: UUID
    product_id: UUID
    quantity: Decimal
    lot_reference: str | None
    has_quantity_divergence: bool
    has_specification_divergence: bool


@dataclass(frozen=True, slots=True)
class QualityInspectionResult:
    company_id: UUID
    goods_receipt_id: UUID
    receipt_item_id: UUID
    inspection_id: UUID
    disposition: InspectionDisposition
    approved_quantity: Decimal
    rejected_quantity: Decimal
    quarantine_quantity: Decimal
    reason_code: str | None

    @classmethod
    def create(
        cls,
        *,
        item: ReceiptItem,
        inspection_id: UUID,
        disposition: InspectionDisposition,
        approved_quantity: Decimal | str | int = 0,
        rejected_quantity: Decimal | str | int = 0,
        quarantine_quantity: Decimal | str | int = 0,
        reason_code: str | None = None,
    ) -> QualityInspectionResult:
        if not isinstance(item, ReceiptItem):
            raise InvalidGoodsReceiptError("item must be a receipt item.")
        if not isinstance(disposition, InspectionDisposition):
            raise InvalidGoodsReceiptError("disposition must be an M17 decision.")
        approved = _non_negative_quantity(approved_quantity, "approved_quantity")
        rejected = _non_negative_quantity(rejected_quantity, "rejected_quantity")
        quarantine = _non_negative_quantity(quarantine_quantity, "quarantine_quantity")
        if approved + rejected + quarantine != item.received_quantity:
            raise InvalidGoodsReceiptError(
                "inspection quantities must equal the physically received quantity."
            )
        if disposition is InspectionDisposition.APPROVE and (
            approved != item.received_quantity or rejected or quarantine
        ):
            raise InvalidGoodsReceiptError("APPROVE must approve the complete receipt item.")
        if disposition is InspectionDisposition.REJECT and (
            rejected != item.received_quantity or approved or quarantine
        ):
            raise InvalidGoodsReceiptError("REJECT must reject the complete receipt item.")
        if disposition is InspectionDisposition.QUARANTINE and (
            quarantine != item.received_quantity or approved or rejected
        ):
            raise InvalidGoodsReceiptError("QUARANTINE must quarantine the complete receipt item.")
        if disposition is InspectionDisposition.PARTIAL_ACCEPTANCE and (
            approved <= 0 or rejected + quarantine <= 0
        ):
            raise InvalidGoodsReceiptError(
                "PARTIAL_ACCEPTANCE requires approved and non-approved quantities."
            )
        try:
            normalized_reason = (
                None if reason_code is None else identifier(reason_code, "reason_code", maximum=64)
            )
            normalized_inspection_id = require_uuid(inspection_id, "inspection_id")
        except ProcurementDomainError as error:
            raise InvalidGoodsReceiptError(str(error)) from error
        if disposition is not InspectionDisposition.APPROVE and normalized_reason is None:
            raise InvalidGoodsReceiptError("a non-approved inspection requires a reason_code.")
        return cls(
            company_id=item.company_id,
            goods_receipt_id=item.goods_receipt_id,
            receipt_item_id=item.id,
            inspection_id=normalized_inspection_id,
            disposition=disposition,
            approved_quantity=approved,
            rejected_quantity=rejected,
            quarantine_quantity=quarantine,
            reason_code=normalized_reason,
        )


@dataclass(frozen=True, slots=True)
class InventoryReceiptPostingRequest:
    id: UUID
    company_id: UUID
    goods_receipt_id: UUID
    receipt_item_id: UUID
    product_id: UUID
    warehouse_id: UUID
    lot_reference: str | None
    quantity: Decimal
    state: InventoryReceiptState
    quality_inspection_id: UUID


@dataclass(frozen=True, slots=True)
class InventoryPostingConfirmation:
    posting_request_id: UUID
    inventory_transaction_id: UUID

    @classmethod
    def create(
        cls, *, posting_request_id: UUID, inventory_transaction_id: UUID
    ) -> InventoryPostingConfirmation:
        try:
            return cls(
                require_uuid(posting_request_id, "posting_request_id"),
                require_uuid(inventory_transaction_id, "inventory_transaction_id"),
            )
        except ProcurementDomainError as error:
            raise InvalidGoodsReceiptError(str(error)) from error


@dataclass(frozen=True, slots=True)
class GoodsReceipt:
    id: UUID
    company_id: UUID
    number: str
    purchase_order_id: UUID
    supplier_id: UUID
    warehouse_id: UUID
    received_by: UUID
    status: GoodsReceiptStatus
    items: tuple[ReceiptItem, ...]
    inspection_results: tuple[QualityInspectionResult, ...]
    posting_requests: tuple[InventoryReceiptPostingRequest, ...]
    inventory_transaction_ids: tuple[UUID, ...]
    physically_received_at: datetime | None
    version: int

    @classmethod
    def create_from_purchase_order(
        cls,
        *,
        company_id: UUID,
        number: str,
        purchase_order: PurchaseOrder,
        warehouse_id: UUID,
        received_by: UUID,
        tolerance: ReceiptTolerance,
        lines: tuple[tuple[UUID, Decimal | str | int, bool, str | None, str | None], ...],
    ) -> GoodsReceipt:
        if not isinstance(purchase_order, PurchaseOrder):
            raise InvalidGoodsReceiptError("purchase_order must be a PurchaseOrder.")
        if purchase_order.company_id != company_id:
            raise InvalidGoodsReceiptError("purchase order is outside the receipt company.")
        if purchase_order.status not in {
            PurchaseOrderStatus.ISSUED,
            PurchaseOrderStatus.PARTIALLY_RECEIVED,
        }:
            raise InvalidGoodsReceiptError("only issued purchase orders can originate a receipt.")
        if not isinstance(tolerance, ReceiptTolerance):
            raise InvalidGoodsReceiptError("tolerance must be a ReceiptTolerance.")
        if not lines or len({line[0] for line in lines}) != len(lines):
            raise InvalidGoodsReceiptError("receipt lines must contain unique order item ids.")
        order_items = {item.id: item for item in purchase_order.items}
        if not {line[0] for line in lines}.issubset(order_items):
            raise InvalidGoodsReceiptError("receipt references an item outside the purchase order.")
        try:
            receipt_id = uuid4()
            items = tuple(
                ReceiptItem.create(
                    company_id=company_id,
                    goods_receipt_id=receipt_id,
                    order_item=order_items[item_id],
                    received_quantity=received,
                    tolerance=tolerance,
                    specification_conforms=conforms,
                    discrepancy_note=note,
                    lot_reference=lot,
                )
                for item_id, received, conforms, note, lot in lines
            )
            return cls(
                id=receipt_id,
                company_id=require_uuid(company_id, "company_id"),
                number=identifier(number, "number"),
                purchase_order_id=purchase_order.id,
                supplier_id=purchase_order.supplier_id,
                warehouse_id=require_uuid(warehouse_id, "warehouse_id"),
                received_by=require_uuid(received_by, "received_by"),
                status=GoodsReceiptStatus.DRAFT,
                items=items,
                inspection_results=(),
                posting_requests=(),
                inventory_transaction_ids=(),
                physically_received_at=None,
                version=1,
            )
        except ProcurementDomainError as error:
            if isinstance(error, InvalidGoodsReceiptError):
                raise
            raise InvalidGoodsReceiptError(str(error)) from error

    def confirm_received(self, *, occurred_at: datetime | None = None) -> GoodsReceipt:
        if self.status is not GoodsReceiptStatus.DRAFT:
            raise InvalidProcurementTransitionError("only draft receipts can be confirmed.")
        timestamp = occurred_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise InvalidGoodsReceiptError("physically received timestamp must be timezone-aware.")
        return replace(
            self,
            status=GoodsReceiptStatus.RECEIVED,
            physically_received_at=timestamp,
            version=self.version + 1,
        )

    def inspection_requests(self) -> tuple[IncomingInspectionRequest, ...]:
        if self.status is not GoodsReceiptStatus.RECEIVED:
            raise InvalidProcurementTransitionError(
                "inspection can be requested only for received goods."
            )
        return tuple(
            IncomingInspectionRequest(
                company_id=self.company_id,
                goods_receipt_id=self.id,
                receipt_item_id=item.id,
                purchase_order_id=self.purchase_order_id,
                product_id=item.product_id,
                quantity=item.received_quantity,
                lot_reference=item.lot_reference,
                has_quantity_divergence=item.quantity_variance != 0,
                has_specification_divergence=not item.specification_conforms,
            )
            for item in self.items
        )

    def apply_inspection_results(
        self, results: tuple[QualityInspectionResult, ...]
    ) -> GoodsReceipt:
        if self.status is not GoodsReceiptStatus.RECEIVED:
            raise InvalidProcurementTransitionError(
                "inspection results require a received goods receipt."
            )
        expected_ids = {item.id for item in self.items}
        if (
            len(results) != len(self.items)
            or {result.receipt_item_id for result in results} != expected_ids
        ):
            raise InvalidGoodsReceiptError(
                "inspection results must cover every receipt item exactly once."
            )
        if any(
            result.company_id != self.company_id or result.goods_receipt_id != self.id
            for result in results
        ):
            raise InvalidGoodsReceiptError("inspection result is outside the receipt scope.")
        if sum((result.approved_quantity for result in results), Decimal("0.000000")) == 0:
            return replace(
                self,
                status=GoodsReceiptStatus.REJECTED,
                inspection_results=results,
                version=self.version + 1,
            )
        requests = _posting_requests(self, results)
        return replace(
            self,
            status=GoodsReceiptStatus.INSPECTED,
            inspection_results=results,
            posting_requests=requests,
            version=self.version + 1,
        )

    def confirm_inventory_posting(
        self, confirmations: tuple[InventoryPostingConfirmation, ...]
    ) -> GoodsReceipt:
        if self.status is not GoodsReceiptStatus.INSPECTED:
            raise InvalidProcurementTransitionError(
                "inventory posting requires an inspected goods receipt."
            )
        expected = {request.id for request in self.posting_requests}
        actual = {confirmation.posting_request_id for confirmation in confirmations}
        if len(confirmations) != len(expected) or actual != expected:
            raise InvalidGoodsReceiptError(
                "inventory confirmations must cover every posting request exactly once."
            )
        transaction_ids = tuple(
            require_uuid(confirmation.inventory_transaction_id, "inventory_transaction_id")
            for confirmation in confirmations
        )
        if len(set(transaction_ids)) != len(transaction_ids):
            raise InvalidGoodsReceiptError("inventory transaction ids must be unique.")
        return replace(
            self,
            status=GoodsReceiptStatus.POSTED,
            inventory_transaction_ids=transaction_ids,
            version=self.version + 1,
        )


def _posting_requests(
    receipt: GoodsReceipt, results: tuple[QualityInspectionResult, ...]
) -> tuple[InventoryReceiptPostingRequest, ...]:
    items = {item.id: item for item in receipt.items}
    requests: list[InventoryReceiptPostingRequest] = []
    for result in results:
        item = items[result.receipt_item_id]
        if result.approved_quantity:
            requests.append(
                _posting_request(
                    receipt, item, result, result.approved_quantity, InventoryReceiptState.AVAILABLE
                )
            )
        held_quantity = result.rejected_quantity + result.quarantine_quantity
        if held_quantity:
            requests.append(
                _posting_request(
                    receipt, item, result, held_quantity, InventoryReceiptState.QUARANTINE
                )
            )
    return tuple(requests)


def _posting_request(
    receipt: GoodsReceipt,
    item: ReceiptItem,
    result: QualityInspectionResult,
    posting_quantity: Decimal,
    state: InventoryReceiptState,
) -> InventoryReceiptPostingRequest:
    return InventoryReceiptPostingRequest(
        id=uuid4(),
        company_id=receipt.company_id,
        goods_receipt_id=receipt.id,
        receipt_item_id=item.id,
        product_id=item.product_id,
        warehouse_id=receipt.warehouse_id,
        lot_reference=item.lot_reference,
        quantity=posting_quantity,
        state=state,
        quality_inspection_id=result.inspection_id,
    )


def _non_negative_quantity(value: Decimal | str | int, field: str) -> Decimal:
    normalized = _decimal(value, field, _QUANTITY_QUANTUM)
    if normalized < 0:
        raise InvalidGoodsReceiptError(f"{field} cannot be negative.")
    return normalized


def _decimal(value: Decimal | str | int, field: str, quantum: Decimal) -> Decimal:
    try:
        normalized = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as error:
        raise InvalidGoodsReceiptError(f"{field} must be a valid decimal.") from error
    if not normalized.is_finite():
        raise InvalidGoodsReceiptError(f"{field} must be finite.")
    return normalized


__all__ = [
    "GoodsReceipt",
    "GoodsReceiptStatus",
    "IncomingInspectionRequest",
    "InspectionDisposition",
    "InventoryPostingConfirmation",
    "InventoryReceiptPostingRequest",
    "InventoryReceiptState",
    "QualityInspectionResult",
    "ReceiptItem",
    "ReceiptQuantityVariance",
    "ReceiptTolerance",
]
