"""Authorized application contracts for M6 physical goods receiving."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.procurement.application.permissions import (
    PROCUREMENT_RECEIPT_MANAGE,
    PROCUREMENT_RECEIPT_READ,
    ProcurementAuthorization,
)
from erp.modules.procurement.application.purchasing import ProcurementCommandMetadata
from erp.modules.procurement.domain import (
    GoodsReceipt,
    GoodsReceiptStatus,
    InspectionDisposition,
)
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class GoodsReceiptLineInput:
    purchase_order_item_id: UUID
    received_quantity: Decimal
    specification_conforms: bool
    discrepancy_note: str | None = None
    lot_reference: str | None = None


@dataclass(frozen=True, slots=True)
class CreateGoodsReceipt:
    company_id: UUID
    number: str
    purchase_order_id: UUID
    warehouse_id: UUID
    tolerance_percentage: Decimal
    lines: tuple[GoodsReceiptLineInput, ...]
    idempotency_key: str
    metadata: ProcurementCommandMetadata = field(default_factory=ProcurementCommandMetadata.new)

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "number": self.number,
            "purchase_order_id": str(self.purchase_order_id),
            "warehouse_id": str(self.warehouse_id),
            "tolerance_percentage": str(self.tolerance_percentage),
            "lines": [
                {
                    "purchase_order_item_id": str(line.purchase_order_item_id),
                    "received_quantity": str(line.received_quantity),
                    "specification_conforms": line.specification_conforms,
                    "discrepancy_note": line.discrepancy_note,
                    "lot_reference": line.lot_reference,
                }
                for line in self.lines
            ],
        }


@dataclass(frozen=True, slots=True)
class ReceiveGoodsReceipt:
    company_id: UUID
    receipt_id: UUID
    expected_version: int
    idempotency_key: str
    occurred_at: datetime | None = None
    metadata: ProcurementCommandMetadata = field(default_factory=ProcurementCommandMetadata.new)

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "receipt_id": str(self.receipt_id),
            "expected_version": self.expected_version,
            "occurred_at": None if self.occurred_at is None else self.occurred_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class InspectionDecisionInput:
    receipt_item_id: UUID
    inspection_id: UUID
    disposition: InspectionDisposition
    approved_quantity: Decimal
    rejected_quantity: Decimal
    quarantine_quantity: Decimal
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class InspectGoodsReceipt:
    company_id: UUID
    receipt_id: UUID
    expected_version: int
    decisions: tuple[InspectionDecisionInput, ...]
    idempotency_key: str
    metadata: ProcurementCommandMetadata = field(default_factory=ProcurementCommandMetadata.new)

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "receipt_id": str(self.receipt_id),
            "expected_version": self.expected_version,
            "decisions": [
                {
                    "receipt_item_id": str(value.receipt_item_id),
                    "inspection_id": str(value.inspection_id),
                    "disposition": value.disposition.value,
                    "approved_quantity": str(value.approved_quantity),
                    "rejected_quantity": str(value.rejected_quantity),
                    "quarantine_quantity": str(value.quarantine_quantity),
                    "reason_code": value.reason_code,
                }
                for value in self.decisions
            ],
        }


@dataclass(frozen=True, slots=True)
class PostGoodsReceiptToInventory:
    company_id: UUID
    receipt_id: UUID
    expected_version: int
    idempotency_key: str
    metadata: ProcurementCommandMetadata = field(default_factory=ProcurementCommandMetadata.new)

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "receipt_id": str(self.receipt_id),
            "expected_version": self.expected_version,
        }


@dataclass(frozen=True, slots=True)
class GoodsReceiptPage:
    items: tuple[GoodsReceipt, ...]
    page: int
    page_size: int
    has_more: bool


class GoodsReceiptStore(Protocol):
    async def create(self, command: CreateGoodsReceipt, *, actor_id: UUID) -> GoodsReceipt: ...
    async def receive(self, command: ReceiveGoodsReceipt, *, actor_id: UUID) -> GoodsReceipt: ...
    async def inspect(self, command: InspectGoodsReceipt, *, actor_id: UUID) -> GoodsReceipt: ...
    async def post_to_inventory(
        self, command: PostGoodsReceiptToInventory, *, actor_id: UUID
    ) -> GoodsReceipt: ...
    async def get(self, company_id: UUID, receipt_id: UUID) -> GoodsReceipt | None: ...
    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        purchase_order_id: UUID | None,
        supplier_id: UUID | None,
        status: GoodsReceiptStatus | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> GoodsReceiptPage: ...


class GoodsReceiptService:
    def __init__(self, store: GoodsReceiptStore, authorization: ProcurementAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create(self, context: SecurityContext, command: CreateGoodsReceipt) -> GoodsReceipt:
        await self._manage(context, command.company_id)
        return await self._store.create(command, actor_id=context.principal.user_id)

    async def receive(self, context: SecurityContext, command: ReceiveGoodsReceipt) -> GoodsReceipt:
        await self._manage(context, command.company_id)
        return await self._store.receive(command, actor_id=context.principal.user_id)

    async def inspect(self, context: SecurityContext, command: InspectGoodsReceipt) -> GoodsReceipt:
        await self._manage(context, command.company_id)
        return await self._store.inspect(command, actor_id=context.principal.user_id)

    async def post_to_inventory(
        self, context: SecurityContext, command: PostGoodsReceiptToInventory
    ) -> GoodsReceipt:
        await self._manage(context, command.company_id)
        return await self._store.post_to_inventory(command, actor_id=context.principal.user_id)

    async def get(
        self, context: SecurityContext, company_id: UUID, receipt_id: UUID
    ) -> GoodsReceipt:
        await self._authorization.require(context, company_id, PROCUREMENT_RECEIPT_READ)
        value = await self._store.get(company_id, receipt_id)
        if value is None:
            raise _not_found()
        return value

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        purchase_order_id: UUID | None,
        supplier_id: UUID | None,
        status: GoodsReceiptStatus | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> GoodsReceiptPage:
        await self._authorization.require(context, company_id, PROCUREMENT_RECEIPT_READ)
        if not 1 <= page <= 100_000 or not 1 <= page_size <= 100:
            raise ApplicationError(
                code="VALIDATION_ERROR", message="Invalid pagination.", status_code=422
            )
        if created_from is not None and created_to is not None and created_from > created_to:
            raise ApplicationError(
                code="VALIDATION_ERROR",
                message="created_from must not exceed created_to.",
                status_code=422,
            )
        return await self._store.list(
            company_id,
            page=page,
            page_size=page_size,
            purchase_order_id=purchase_order_id,
            supplier_id=supplier_id,
            status=status,
            created_from=created_from,
            created_to=created_to,
        )

    async def _manage(self, context: SecurityContext, company_id: UUID) -> None:
        await self._authorization.require(
            context, company_id, PROCUREMENT_RECEIPT_MANAGE, write=True
        )


def _not_found() -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND", message="Goods receipt not found.", status_code=404
    )


__all__ = [name for name in globals() if not name.startswith("_")]
