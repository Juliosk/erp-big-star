"""HTTP contracts for M6 purchase requisitions and purchase orders."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.procurement.application.purchasing import PurchaseOrderPage, RequisitionPage
from erp.modules.procurement.domain import PurchaseOrder, PurchaseRequisition, RequisitionUrgency


class RequisitionLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    quantity: Decimal = Field(gt=0, decimal_places=6)
    unit_of_measure: str = Field(min_length=1, max_length=16)
    needed_by: date
    urgency: RequisitionUrgency = RequisitionUrgency.NORMAL
    specification: str = Field(min_length=1, max_length=1000)


class CreateRequisitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    number: str = Field(min_length=1, max_length=64)
    cost_center_id: UUID
    justification: str = Field(min_length=1, max_length=1000)
    items: list[RequisitionLineRequest] = Field(min_length=1, max_length=500)


class RequisitionItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    quantity: Decimal
    unit_of_measure: str
    needed_by: date
    urgency: str
    specification: str


class RequisitionResponse(BaseModel):
    id: UUID
    company_id: UUID
    number: str
    requester_id: UUID
    cost_center_id: UUID
    status: str
    justification: str
    deadline: date
    urgency: str
    version: int
    items: list[RequisitionItemResponse]

    @classmethod
    def from_domain(cls, value: PurchaseRequisition) -> RequisitionResponse:
        return cls(
            id=value.id,
            company_id=value.company_id,
            number=value.number,
            requester_id=value.requester_id,
            cost_center_id=value.cost_center_id,
            status=value.status,
            justification=value.justification,
            deadline=value.deadline,
            urgency=value.urgency,
            version=value.version,
            items=[
                RequisitionItemResponse(
                    id=item.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_of_measure=item.unit_of_measure,
                    needed_by=item.needed_by,
                    urgency=item.urgency,
                    specification=item.specification,
                )
                for item in value.items
            ],
        )


class PageMeta(BaseModel):
    page: int
    page_size: int
    has_more: bool


class RequisitionListResponse(BaseModel):
    data: list[RequisitionResponse]
    meta: PageMeta

    @classmethod
    def from_page(cls, value: RequisitionPage) -> RequisitionListResponse:
        return cls(
            data=[RequisitionResponse.from_domain(item) for item in value.items],
            meta=PageMeta(page=value.page, page_size=value.page_size, has_more=value.has_more),
        )


class PurchaseOrderLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requisition_item_id: UUID
    quantity: Decimal = Field(gt=0, decimal_places=6)
    unit_price: Decimal = Field(ge=0, decimal_places=2)


class CreatePurchaseOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    number: str = Field(min_length=1, max_length=64)
    source_requisition_id: UUID
    supplier_id: UUID
    currency: str = Field(min_length=3, max_length=3)
    payment_terms_code: str = Field(min_length=1, max_length=32)
    payment_terms_description: str = Field(min_length=1, max_length=200)
    installment_days: list[int] = Field(min_length=1, max_length=60)
    items: list[PurchaseOrderLineRequest] = Field(min_length=1, max_length=500)


class ReceiptLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: UUID
    quantity: Decimal = Field(gt=0, decimal_places=6)


class ReceivePurchaseOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ReceiptLineRequest] = Field(min_length=1, max_length=500)


class PurchaseOrderItemResponse(BaseModel):
    id: UUID
    requisition_item_id: UUID
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal
    currency: str
    received_quantity: Decimal
    outstanding_quantity: Decimal
    line_total: Decimal


class PurchaseOrderResponse(BaseModel):
    id: UUID
    company_id: UUID
    number: str
    supplier_id: UUID
    source_requisition_id: UUID
    buyer_id: UUID
    currency: str
    payment_terms_code: str
    payment_terms_description: str
    installment_days: list[int]
    status: str
    total_amount: Decimal
    version: int
    items: list[PurchaseOrderItemResponse]

    @classmethod
    def from_domain(cls, value: PurchaseOrder) -> PurchaseOrderResponse:
        return cls(
            id=value.id,
            company_id=value.company_id,
            number=value.number,
            supplier_id=value.supplier_id,
            source_requisition_id=value.source_requisition_id,
            buyer_id=value.buyer_id,
            currency=value.currency,
            payment_terms_code=value.payment_terms.code,
            payment_terms_description=value.payment_terms.description,
            installment_days=list(value.payment_terms.installment_days),
            status=value.status,
            total_amount=value.total_amount,
            version=value.version,
            items=[
                PurchaseOrderItemResponse(
                    id=item.id,
                    requisition_item_id=item.requisition_item_id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    currency=item.currency,
                    received_quantity=item.received_quantity,
                    outstanding_quantity=item.outstanding_quantity,
                    line_total=item.line_total,
                )
                for item in value.items
            ],
        )


class PurchaseOrderListResponse(BaseModel):
    data: list[PurchaseOrderResponse]
    meta: PageMeta

    @classmethod
    def from_page(cls, value: PurchaseOrderPage) -> PurchaseOrderListResponse:
        return cls(
            data=[PurchaseOrderResponse.from_domain(item) for item in value.items],
            meta=PageMeta(page=value.page, page_size=value.page_size, has_more=value.has_more),
        )


__all__ = [name for name in globals() if name.endswith(("Request", "Response"))]
