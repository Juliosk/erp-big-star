"""Tenant-bound persistence adapter for the M6 GoodsReceipt aggregate."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.domain import (
    GoodsReceipt,
    GoodsReceiptStatus,
    InspectionDisposition,
    InventoryReceiptPostingRequest,
    InventoryReceiptState,
    QualityInspectionResult,
    ReceiptItem,
    ReceiptTolerance,
)
from erp.modules.procurement.infrastructure.goods_receipt_model import (
    GoodsReceiptModel,
    ReceiptItemModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


class GoodsReceiptConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="GOODS_RECEIPT_CONFLICT",
            message="A goods receipt number already exists for this company.",
            status_code=409,
        )


def _receipt_item(model: ReceiptItemModel) -> ReceiptItem:
    return ReceiptItem(
        id=model.id,
        company_id=model.company_id,
        goods_receipt_id=model.goods_receipt_id,
        purchase_order_item_id=model.purchase_order_item_id,
        product_id=model.product_id,
        ordered_quantity=model.ordered_quantity,
        previously_received_quantity=model.previously_received_quantity,
        expected_quantity=model.expected_quantity,
        received_quantity=model.received_quantity,
        tolerance=ReceiptTolerance(model.tolerance_percentage),
        specification_conforms=model.specification_conforms,
        discrepancy_note=model.discrepancy_note,
        lot_reference=model.lot_reference,
    )


def _inspection_result(
    model: ReceiptItemModel, item: ReceiptItem
) -> QualityInspectionResult | None:
    if model.inspection_id is None or model.inspection_disposition is None:
        return None
    return QualityInspectionResult(
        company_id=item.company_id,
        goods_receipt_id=item.goods_receipt_id,
        receipt_item_id=item.id,
        inspection_id=model.inspection_id,
        disposition=InspectionDisposition(model.inspection_disposition),
        approved_quantity=model.approved_quantity,
        rejected_quantity=model.rejected_quantity,
        quarantine_quantity=model.quarantine_quantity,
        reason_code=model.inspection_reason_code,
    )


def _posting_requests(
    root: GoodsReceiptModel,
    model: ReceiptItemModel,
    item: ReceiptItem,
) -> tuple[InventoryReceiptPostingRequest, ...]:
    if model.inspection_id is None:
        return ()
    requests: list[InventoryReceiptPostingRequest] = []
    if model.available_posting_request_id is not None:
        requests.append(
            InventoryReceiptPostingRequest(
                id=model.available_posting_request_id,
                company_id=item.company_id,
                goods_receipt_id=item.goods_receipt_id,
                receipt_item_id=item.id,
                product_id=item.product_id,
                warehouse_id=root.warehouse_id,
                lot_reference=item.lot_reference,
                quantity=model.approved_quantity,
                state=InventoryReceiptState.AVAILABLE,
                quality_inspection_id=model.inspection_id,
            )
        )
    held_quantity = model.rejected_quantity + model.quarantine_quantity
    if model.quarantine_posting_request_id is not None:
        requests.append(
            InventoryReceiptPostingRequest(
                id=model.quarantine_posting_request_id,
                company_id=item.company_id,
                goods_receipt_id=item.goods_receipt_id,
                receipt_item_id=item.id,
                product_id=item.product_id,
                warehouse_id=root.warehouse_id,
                lot_reference=item.lot_reference,
                quantity=held_quantity,
                state=InventoryReceiptState.QUARANTINE,
                quality_inspection_id=model.inspection_id,
            )
        )
    return tuple(requests)


def _receipt(root: GoodsReceiptModel, models: tuple[ReceiptItemModel, ...]) -> GoodsReceipt:
    items = tuple(_receipt_item(model) for model in models)
    results = tuple(
        result
        for model, item in zip(models, items, strict=True)
        if (result := _inspection_result(model, item)) is not None
    )
    requests = tuple(
        request
        for model, item in zip(models, items, strict=True)
        for request in _posting_requests(root, model, item)
    )
    transaction_ids = tuple(
        transaction_id
        for model in models
        for transaction_id in (
            model.available_inventory_transaction_id,
            model.quarantine_inventory_transaction_id,
        )
        if transaction_id is not None
    )
    return GoodsReceipt(
        id=root.id,
        company_id=root.company_id,
        number=root.number,
        purchase_order_id=root.purchase_order_id,
        supplier_id=root.supplier_id,
        warehouse_id=root.warehouse_id,
        received_by=root.received_by,
        status=GoodsReceiptStatus(root.status),
        items=items,
        inspection_results=results,
        posting_requests=requests,
        inventory_transaction_ids=transaction_ids,
        physically_received_at=root.physically_received_at,
        version=root.version,
    )


class GoodsReceiptRepository:
    """Persist receipts without owning commit or rollback boundaries."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, receipt: GoodsReceipt, *, actor_id: UUID) -> None:
        self._write_scope(receipt, actor_id)
        if receipt.version != 1 or receipt.status is not GoodsReceiptStatus.DRAFT:
            raise ValueError("A new goods receipt must start draft at version one.")
        self._validate_item_scope(receipt)
        self._session.add(
            GoodsReceiptModel(
                id=receipt.id,
                company_id=self._company_id,
                number=receipt.number,
                purchase_order_id=receipt.purchase_order_id,
                supplier_id=receipt.supplier_id,
                warehouse_id=receipt.warehouse_id,
                received_by=receipt.received_by,
                status=receipt.status,
                physically_received_at=receipt.physically_received_at,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush()
        self._session.add_all(
            [
                ReceiptItemModel(
                    id=item.id,
                    company_id=self._company_id,
                    goods_receipt_id=receipt.id,
                    line_number=line_number,
                    purchase_order_item_id=item.purchase_order_item_id,
                    product_id=item.product_id,
                    ordered_quantity=item.ordered_quantity,
                    previously_received_quantity=item.previously_received_quantity,
                    expected_quantity=item.expected_quantity,
                    received_quantity=item.received_quantity,
                    tolerance_percentage=item.tolerance.max_overage_percentage,
                    specification_conforms=item.specification_conforms,
                    discrepancy_note=item.discrepancy_note,
                    lot_reference=item.lot_reference,
                    approved_quantity=0,
                    rejected_quantity=0,
                    quarantine_quantity=0,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                for line_number, item in enumerate(receipt.items, start=1)
            ]
        )
        await self._flush()

    async def get(self, receipt_id: UUID) -> GoodsReceipt | None:
        root = await self._session.scalar(
            select(GoodsReceiptModel)
            .where(
                GoodsReceiptModel.company_id == self._company_id,
                GoodsReceiptModel.id == receipt_id,
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return _receipt(root, await self._items(receipt_id))

    async def list(
        self,
        *,
        status: GoodsReceiptStatus | None = None,
        purchase_order_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[GoodsReceipt, ...]:
        self._page(limit, offset)
        statement = select(GoodsReceiptModel).where(
            GoodsReceiptModel.company_id == self._company_id
        )
        if status is not None:
            if not isinstance(status, GoodsReceiptStatus):
                raise ValueError("status must be an official goods receipt status.")
            statement = statement.where(GoodsReceiptModel.status == status)
        if purchase_order_id is not None:
            statement = statement.where(GoodsReceiptModel.purchase_order_id == purchase_order_id)
        roots = await self._session.scalars(
            statement.order_by(GoodsReceiptModel.number, GoodsReceiptModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        result = []
        for root in roots:
            result.append(_receipt(root, await self._items(root.id)))
        return tuple(result)

    async def save(
        self,
        receipt: GoodsReceipt,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> GoodsReceipt:
        self._write_scope(receipt, actor_id)
        self._validate_item_scope(receipt)
        compare = receipt.version - 1 if expected_version is None else expected_version
        if compare < 1 or receipt.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        updated = cast(
            CursorResult[Any],
            await self._session.execute(
                update(GoodsReceiptModel)
                .where(
                    GoodsReceiptModel.company_id == self._company_id,
                    GoodsReceiptModel.id == receipt.id,
                    GoodsReceiptModel.version == compare,
                    GoodsReceiptModel.number == receipt.number,
                    GoodsReceiptModel.purchase_order_id == receipt.purchase_order_id,
                    GoodsReceiptModel.supplier_id == receipt.supplier_id,
                )
                .values(
                    status=receipt.status,
                    physically_received_at=receipt.physically_received_at,
                    version=receipt.version,
                    updated_at=datetime.now(UTC),
                    updated_by=actor_id,
                )
            ),
        )
        if updated.rowcount != 1:
            raise OptimisticLockError(expected_version=compare)

        current_items = await self._items(receipt.id)
        if {item.id for item in current_items} != {item.id for item in receipt.items}:
            raise ApplicationError(
                code="GOODS_RECEIPT_ITEM_CONFLICT",
                message="The persisted receipt items no longer match the aggregate.",
                status_code=409,
            )
        results = {result.receipt_item_id: result for result in receipt.inspection_results}
        requests = {
            (request.receipt_item_id, request.state): request
            for request in receipt.posting_requests
        }
        transactions = (
            dict(zip(receipt.posting_requests, receipt.inventory_transaction_ids, strict=True))
            if receipt.inventory_transaction_ids
            else {}
        )
        for item in receipt.items:
            result = results.get(item.id)
            available = requests.get((item.id, InventoryReceiptState.AVAILABLE))
            quarantine = requests.get((item.id, InventoryReceiptState.QUARANTINE))
            item_update = cast(
                CursorResult[Any],
                await self._session.execute(
                    update(ReceiptItemModel)
                    .where(
                        ReceiptItemModel.company_id == self._company_id,
                        ReceiptItemModel.goods_receipt_id == receipt.id,
                        ReceiptItemModel.id == item.id,
                    )
                    .values(
                        inspection_id=None if result is None else result.inspection_id,
                        inspection_disposition=None if result is None else result.disposition,
                        approved_quantity=0 if result is None else result.approved_quantity,
                        rejected_quantity=0 if result is None else result.rejected_quantity,
                        quarantine_quantity=0 if result is None else result.quarantine_quantity,
                        inspection_reason_code=None if result is None else result.reason_code,
                        available_posting_request_id=None if available is None else available.id,
                        quarantine_posting_request_id=None if quarantine is None else quarantine.id,
                        available_inventory_transaction_id=(
                            None if available is None else transactions.get(available)
                        ),
                        quarantine_inventory_transaction_id=(
                            None if quarantine is None else transactions.get(quarantine)
                        ),
                        updated_at=datetime.now(UTC),
                        updated_by=actor_id,
                    )
                ),
            )
            if item_update.rowcount != 1:
                raise ApplicationError(
                    code="GOODS_RECEIPT_ITEM_CONFLICT",
                    message="A goods receipt item no longer exists.",
                    status_code=409,
                )
        await self._session.flush()
        return receipt

    def _write_scope(self, receipt: GoodsReceipt, actor_id: UUID) -> None:
        if receipt.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The resource is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    def _validate_item_scope(self, receipt: GoodsReceipt) -> None:
        if any(
            item.company_id != self._company_id or item.goods_receipt_id != receipt.id
            for item in receipt.items
        ):
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="A goods receipt item is outside the aggregate scope.",
                status_code=403,
            )

    @staticmethod
    def _page(limit: int, offset: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100.")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer.")

    async def _items(self, receipt_id: UUID) -> tuple[ReceiptItemModel, ...]:
        items = await self._session.scalars(
            select(ReceiptItemModel)
            .where(
                ReceiptItemModel.company_id == self._company_id,
                ReceiptItemModel.goods_receipt_id == receipt_id,
            )
            .order_by(ReceiptItemModel.line_number)
        )
        return tuple(items)

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise GoodsReceiptConflictError from error
            raise


__all__ = [
    "GoodsReceiptConflictError",
    "GoodsReceiptRepository",
    "_receipt",
    "_receipt_item",
]
