"""Pure purchase order aggregate owned by M6 Procurement."""

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.procurement.domain.approval import ApprovalRequest, ApprovalSubjectType
from erp.modules.procurement.domain.exceptions import (
    InvalidProcurementTransitionError,
    InvalidPurchaseOrderError,
    ProcurementDomainError,
)
from erp.modules.procurement.domain.support import (
    currency,
    identifier,
    money,
    quantity,
    require_uuid,
    text,
)


class PurchaseOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class PaymentTerms:
    code: str
    description: str
    installment_days: tuple[int, ...]

    @classmethod
    def create(
        cls, *, code: str, description: str, installment_days: tuple[int, ...]
    ) -> PaymentTerms:
        if (
            not installment_days
            or any(type(day) is not int or day < 0 for day in installment_days)
            or tuple(sorted(set(installment_days))) != installment_days
        ):
            raise InvalidPurchaseOrderError(
                "installment_days must be unique non-negative days in ascending order."
            )
        try:
            return cls(
                code=identifier(code, "payment_terms.code", maximum=32),
                description=text(description, "payment_terms.description", maximum=200),
                installment_days=installment_days,
            )
        except ProcurementDomainError as error:
            raise InvalidPurchaseOrderError(str(error)) from error


@dataclass(frozen=True, slots=True)
class PurchaseOrderItem:
    id: UUID
    company_id: UUID
    purchase_order_id: UUID
    requisition_item_id: UUID
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal
    currency: str
    received_quantity: Decimal

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        purchase_order_id: UUID,
        requisition_item_id: UUID,
        product_id: UUID,
        quantity_value: Decimal | str | int,
        unit_price: Decimal | str | int,
        currency_code: str,
    ) -> PurchaseOrderItem:
        try:
            return cls(
                id=uuid4(),
                company_id=require_uuid(company_id, "company_id"),
                purchase_order_id=require_uuid(purchase_order_id, "purchase_order_id"),
                requisition_item_id=require_uuid(requisition_item_id, "requisition_item_id"),
                product_id=require_uuid(product_id, "product_id"),
                quantity=quantity(quantity_value),
                unit_price=money(unit_price, "unit_price"),
                currency=currency(currency_code),
                received_quantity=Decimal("0.000000"),
            )
        except ProcurementDomainError as error:
            raise InvalidPurchaseOrderError(str(error)) from error

    @property
    def line_total(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def outstanding_quantity(self) -> Decimal:
        return self.quantity - self.received_quantity

    def receive(self, received: Decimal | str | int) -> PurchaseOrderItem:
        try:
            received_value = quantity(received)
        except ProcurementDomainError as error:
            raise InvalidPurchaseOrderError(str(error)) from error
        if received_value > self.outstanding_quantity:
            raise InvalidPurchaseOrderError("received quantity cannot exceed outstanding quantity.")
        return replace(self, received_quantity=self.received_quantity + received_value)


@dataclass(frozen=True, slots=True)
class PurchaseOrder:
    id: UUID
    company_id: UUID
    number: str
    supplier_id: UUID
    source_requisition_id: UUID
    buyer_id: UUID
    currency: str
    payment_terms: PaymentTerms
    status: PurchaseOrderStatus
    items: tuple[PurchaseOrderItem, ...]
    total_amount: Decimal
    version: int

    @classmethod
    def create_from_requisition(
        cls,
        *,
        company_id: UUID,
        number: str,
        supplier_id: UUID,
        source_requisition_id: UUID,
        buyer_id: UUID,
        currency_code: str,
        payment_terms: PaymentTerms,
        lines: tuple[
            tuple[
                UUID,
                UUID,
                Decimal | str | int,
                Decimal | str | int,
                str,
            ],
            ...,
        ],
    ) -> PurchaseOrder:
        if not isinstance(payment_terms, PaymentTerms):
            raise InvalidPurchaseOrderError("payment_terms must be validated PaymentTerms.")
        if not lines:
            raise InvalidPurchaseOrderError("purchase order requires at least one item.")
        try:
            order_id = uuid4()
            normalized_currency = currency(currency_code)
            items = tuple(
                PurchaseOrderItem.create(
                    company_id=company_id,
                    purchase_order_id=order_id,
                    requisition_item_id=requisition_item_id,
                    product_id=product_id,
                    quantity_value=item_quantity,
                    unit_price=unit_price,
                    currency_code=item_currency,
                )
                for (
                    requisition_item_id,
                    product_id,
                    item_quantity,
                    unit_price,
                    item_currency,
                ) in lines
            )
            if any(item.currency != normalized_currency for item in items):
                raise InvalidPurchaseOrderError(
                    "all purchase order items must use the order currency."
                )
            if len({item.requisition_item_id for item in items}) != len(items):
                raise InvalidPurchaseOrderError(
                    "a requisition item can appear only once in a purchase order."
                )
            total = sum((item.line_total for item in items), Decimal("0.00"))
            return cls(
                id=order_id,
                company_id=require_uuid(company_id, "company_id"),
                number=identifier(number, "number"),
                supplier_id=require_uuid(supplier_id, "supplier_id"),
                source_requisition_id=require_uuid(source_requisition_id, "source_requisition_id"),
                buyer_id=require_uuid(buyer_id, "buyer_id"),
                currency=normalized_currency,
                payment_terms=payment_terms,
                status=PurchaseOrderStatus.DRAFT,
                items=items,
                total_amount=total,
                version=1,
            )
        except ProcurementDomainError as error:
            if isinstance(error, InvalidPurchaseOrderError):
                raise
            raise InvalidPurchaseOrderError(str(error)) from error

    def submit_for_approval(self) -> PurchaseOrder:
        if self.status is not PurchaseOrderStatus.DRAFT:
            raise InvalidProcurementTransitionError("only draft purchase orders can be submitted.")
        return replace(
            self,
            status=PurchaseOrderStatus.PENDING_APPROVAL,
            version=self.version + 1,
        )

    def approve(self) -> PurchaseOrder:
        if self.status is not PurchaseOrderStatus.PENDING_APPROVAL:
            raise InvalidProcurementTransitionError("only pending purchase orders can be approved.")
        return replace(self, status=PurchaseOrderStatus.APPROVED, version=self.version + 1)

    def issue(self) -> PurchaseOrder:
        if self.status is not PurchaseOrderStatus.APPROVED:
            raise InvalidProcurementTransitionError("only approved purchase orders can be issued.")
        return replace(self, status=PurchaseOrderStatus.ISSUED, version=self.version + 1)

    def receive(self, receipts: tuple[tuple[UUID, Decimal | str | int], ...]) -> PurchaseOrder:
        if self.status not in {
            PurchaseOrderStatus.ISSUED,
            PurchaseOrderStatus.PARTIALLY_RECEIVED,
        }:
            raise InvalidProcurementTransitionError(
                "only issued purchase orders can receive goods."
            )
        if not receipts or len({item_id for item_id, _ in receipts}) != len(receipts):
            raise InvalidPurchaseOrderError("receipts must contain unique purchase order item ids.")
        receipt_map = dict(receipts)
        known_ids = {item.id for item in self.items}
        if not set(receipt_map).issubset(known_ids):
            raise InvalidPurchaseOrderError(
                "receipt references an item outside the purchase order."
            )
        items = tuple(
            item.receive(receipt_map[item.id]) if item.id in receipt_map else item
            for item in self.items
        )
        status = (
            PurchaseOrderStatus.COMPLETED
            if all(item.outstanding_quantity == 0 for item in items)
            else PurchaseOrderStatus.PARTIALLY_RECEIVED
        )
        return replace(self, items=items, status=status, version=self.version + 1)

    def cancel(self) -> PurchaseOrder:
        allowed = {
            PurchaseOrderStatus.DRAFT,
            PurchaseOrderStatus.PENDING_APPROVAL,
            PurchaseOrderStatus.APPROVED,
            PurchaseOrderStatus.ISSUED,
        }
        if self.status not in allowed or any(item.received_quantity > 0 for item in self.items):
            raise InvalidProcurementTransitionError(
                "purchase order cannot be cancelled after receiving goods."
            )
        return replace(self, status=PurchaseOrderStatus.CANCELLED, version=self.version + 1)

    def approval_request(self) -> ApprovalRequest:
        if self.status is not PurchaseOrderStatus.PENDING_APPROVAL:
            raise InvalidProcurementTransitionError(
                "only pending purchase orders can request approval."
            )
        return ApprovalRequest(
            company_id=self.company_id,
            subject_type=ApprovalSubjectType.PURCHASE_ORDER,
            subject_id=self.id,
            requested_by=self.buyer_id,
            amount=self.total_amount,
            currency=self.currency,
            aggregate_version=self.version,
        )


__all__ = [
    "PaymentTerms",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "PurchaseOrderStatus",
]
