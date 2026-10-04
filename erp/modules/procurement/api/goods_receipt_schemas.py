"""HTTP contracts for M6 physical goods receipts."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.procurement.application.goods_receipts import GoodsReceiptPage
from erp.modules.procurement.domain import GoodsReceipt, InspectionDisposition


class GoodsReceiptLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purchase_order_item_id: UUID
    received_quantity: Decimal = Field(gt=0, decimal_places=6)
    specification_conforms: bool = True
    discrepancy_note: str | None = Field(default=None, max_length=1000)
    lot_reference: str | None = Field(default=None, max_length=64)


class CreateGoodsReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    number: str = Field(min_length=1, max_length=64)
    purchase_order_id: UUID
    warehouse_id: UUID
    tolerance_percentage: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    items: list[GoodsReceiptLineRequest] = Field(min_length=1, max_length=500)


class ReceiveGoodsReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    occurred_at: datetime | None = None


class InspectionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_item_id: UUID
    inspection_id: UUID
    disposition: InspectionDisposition
    approved_quantity: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=6)
    rejected_quantity: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=6)
    quarantine_quantity: Decimal = Field(default=Decimal("0"), ge=0, decimal_places=6)
    reason_code: str | None = Field(default=None, max_length=64)


class InspectGoodsReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[InspectionDecisionRequest] = Field(min_length=1, max_length=500)


class GoodsReceiptItemResponse(BaseModel):
    id: UUID
    purchase_order_item_id: UUID
    product_id: UUID
    ordered_quantity: Decimal
    previously_received_quantity: Decimal
    expected_quantity: Decimal
    received_quantity: Decimal
    quantity_variance: Decimal
    quantity_variance_kind: str
    specification_conforms: bool
    discrepancy_note: str | None
    lot_reference: str | None


class InspectionResultResponse(BaseModel):
    receipt_item_id: UUID
    inspection_id: UUID
    disposition: str
    approved_quantity: Decimal
    rejected_quantity: Decimal
    quarantine_quantity: Decimal
    reason_code: str | None


class InventoryPostingRequestResponse(BaseModel):
    id: UUID
    receipt_item_id: UUID
    product_id: UUID
    warehouse_id: UUID
    quantity: Decimal
    state: str
    quality_inspection_id: UUID


class GoodsReceiptResponse(BaseModel):
    id: UUID
    company_id: UUID
    number: str
    purchase_order_id: UUID
    supplier_id: UUID
    warehouse_id: UUID
    received_by: UUID
    status: str
    physically_received_at: datetime | None
    version: int
    items: list[GoodsReceiptItemResponse]
    inspection_results: list[InspectionResultResponse]
    posting_requests: list[InventoryPostingRequestResponse]
    inventory_transaction_ids: list[UUID]

    @classmethod
    def from_domain(cls, value: GoodsReceipt) -> GoodsReceiptResponse:
        return cls(
            id=value.id,
            company_id=value.company_id,
            number=value.number,
            purchase_order_id=value.purchase_order_id,
            supplier_id=value.supplier_id,
            warehouse_id=value.warehouse_id,
            received_by=value.received_by,
            status=value.status,
            physically_received_at=value.physically_received_at,
            version=value.version,
            items=[
                GoodsReceiptItemResponse(
                    id=item.id,
                    purchase_order_item_id=item.purchase_order_item_id,
                    product_id=item.product_id,
                    ordered_quantity=item.ordered_quantity,
                    previously_received_quantity=item.previously_received_quantity,
                    expected_quantity=item.expected_quantity,
                    received_quantity=item.received_quantity,
                    quantity_variance=item.quantity_variance,
                    quantity_variance_kind=item.quantity_variance_kind,
                    specification_conforms=item.specification_conforms,
                    discrepancy_note=item.discrepancy_note,
                    lot_reference=item.lot_reference,
                )
                for item in value.items
            ],
            inspection_results=[
                InspectionResultResponse(
                    receipt_item_id=result.receipt_item_id,
                    inspection_id=result.inspection_id,
                    disposition=result.disposition,
                    approved_quantity=result.approved_quantity,
                    rejected_quantity=result.rejected_quantity,
                    quarantine_quantity=result.quarantine_quantity,
                    reason_code=result.reason_code,
                )
                for result in value.inspection_results
            ],
            posting_requests=[
                InventoryPostingRequestResponse(
                    id=request.id,
                    receipt_item_id=request.receipt_item_id,
                    product_id=request.product_id,
                    warehouse_id=request.warehouse_id,
                    quantity=request.quantity,
                    state=request.state,
                    quality_inspection_id=request.quality_inspection_id,
                )
                for request in value.posting_requests
            ],
            inventory_transaction_ids=list(value.inventory_transaction_ids),
        )


class GoodsReceiptPageMeta(BaseModel):
    page: int
    page_size: int
    has_more: bool


class GoodsReceiptListResponse(BaseModel):
    data: list[GoodsReceiptResponse]
    meta: GoodsReceiptPageMeta

    @classmethod
    def from_page(cls, value: GoodsReceiptPage) -> GoodsReceiptListResponse:
        return cls(
            data=[GoodsReceiptResponse.from_domain(item) for item in value.items],
            meta=GoodsReceiptPageMeta(
                page=value.page, page_size=value.page_size, has_more=value.has_more
            ),
        )


__all__ = [name for name in globals() if name.endswith(("Request", "Response"))]
