"""HTTP contracts for fiscal and physical receiving reconciliation."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.fiscal.application import (
    FiscalReceivingReconciliation,
    ReconciliationLineMapping,
)


class ReconciliationLineMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inbound_line_number: int = Field(ge=1)
    receipt_item_id: UUID


class ReconcileFiscalReceivingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goods_receipt_id: UUID
    line_mappings: list[ReconciliationLineMappingRequest] = Field(min_length=1, max_length=500)
    price_tolerance: Decimal = Field(default=Decimal("0.01"), ge=0, le=Decimal("1.00"))

    def mappings(self) -> tuple[ReconciliationLineMapping, ...]:
        return tuple(
            ReconciliationLineMapping(value.inbound_line_number, value.receipt_item_id)
            for value in self.line_mappings
        )


class ReconciliationIssueResponse(BaseModel):
    kind: str
    message: str
    inbound_line_number: int | None
    receipt_item_id: UUID | None
    expected: str | None
    actual: str | None


class FiscalReceivingReconciliationResponse(BaseModel):
    id: UUID
    company_id: UUID
    inbound_fiscal_document_id: UUID
    goods_receipt_id: UUID
    purchase_order_id: UUID
    status: str
    issues: list[ReconciliationIssueResponse]
    financial_blocked: bool
    physical_pending: bool
    inventory_transaction_ids: list[UUID]
    version: int
    reconciled_at: datetime

    @classmethod
    def from_domain(
        cls, value: FiscalReceivingReconciliation
    ) -> FiscalReceivingReconciliationResponse:
        return cls(
            id=value.id,
            company_id=value.company_id,
            inbound_fiscal_document_id=value.inbound_fiscal_document_id,
            goods_receipt_id=value.goods_receipt_id,
            purchase_order_id=value.purchase_order_id,
            status=value.status.value,
            issues=[
                ReconciliationIssueResponse(
                    kind=issue.kind.value,
                    message=issue.message,
                    inbound_line_number=issue.inbound_line_number,
                    receipt_item_id=issue.receipt_item_id,
                    expected=issue.expected,
                    actual=issue.actual,
                )
                for issue in value.issues
            ],
            financial_blocked=value.financial_blocked,
            physical_pending=value.physical_pending,
            inventory_transaction_ids=list(value.inventory_transaction_ids),
            version=value.version,
            reconciled_at=value.reconciled_at,
        )


__all__ = [
    "FiscalReceivingReconciliationResponse",
    "ReconcileFiscalReceivingRequest",
]
