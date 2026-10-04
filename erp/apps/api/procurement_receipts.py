"""Composition adapter joining M6 receipt state with M5 physical inventory atomically."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.domain import (
    InventoryPosting,
    InventoryState,
    InventoryTransaction,
    InventoryTransactionType,
)
from erp.modules.inventory.infrastructure.balance_repository import InventoryBalanceRepository
from erp.modules.inventory.infrastructure.ledger_repository import InventoryLedgerRepository
from erp.modules.inventory.infrastructure.lot_model import InventoryLotModel
from erp.modules.procurement.application.goods_receipts import (
    CreateGoodsReceipt,
    GoodsReceiptPage,
    InspectGoodsReceipt,
    PostGoodsReceiptToInventory,
    ReceiveGoodsReceipt,
)
from erp.modules.procurement.domain import (
    GoodsReceipt,
    GoodsReceiptStatus,
    InventoryPostingConfirmation,
    QualityInspectionResult,
    ReceiptTolerance,
)
from erp.modules.procurement.infrastructure.goods_receipt_events import (
    GOODS_RECEIPT_CREATED,
    GOODS_RECEIPT_INSPECTED,
    GOODS_RECEIPT_POSTED,
    GOODS_RECEIPT_RECEIVED,
    record_goods_receipt_event,
)
from erp.modules.procurement.infrastructure.goods_receipt_repository import (
    GoodsReceiptRepository,
)
from erp.modules.procurement.infrastructure.purchasing_repository import PurchaseOrderRepository
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.idempotency import IdempotencyDecision, IdempotencyService


class PostgresGoodsReceiptOperations:
    """Own each command transaction across M6, idempotency and M5 ledger/balance."""

    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def create(self, command: CreateGoodsReceipt, *, actor_id: UUID) -> GoodsReceipt:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=_scope(command.company_id, actor_id),
                operation="procurement.goods-receipt.create",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                return await _replay(session, command.company_id, decision.response_body)
            order = await PurchaseOrderRepository(session, company_id=command.company_id).get(
                command.purchase_order_id
            )
            if order is None:
                raise _not_found("Purchase order")
            try:
                receipt = GoodsReceipt.create_from_purchase_order(
                    company_id=command.company_id,
                    number=command.number,
                    purchase_order=order,
                    warehouse_id=command.warehouse_id,
                    received_by=actor_id,
                    tolerance=ReceiptTolerance.create(command.tolerance_percentage),
                    lines=tuple(
                        (
                            line.purchase_order_item_id,
                            line.received_quantity,
                            line.specification_conforms,
                            line.discrepancy_note,
                            line.lot_reference,
                        )
                        for line in command.lines
                    ),
                )
            except ValueError as error:
                raise _validation("Invalid goods receipt draft.", error) from error
            await GoodsReceiptRepository(session, company_id=command.company_id).add(
                receipt, actor_id=actor_id
            )
            await record_goods_receipt_event(
                session,
                receipt=receipt,
                event_type=GOODS_RECEIPT_CREATED,
                metadata=command.metadata,
            )
            await _complete(self._idempotency, session, decision, receipt, 201)
            return receipt

    async def receive(self, command: ReceiveGoodsReceipt, *, actor_id: UUID) -> GoodsReceipt:
        async with self._database.session() as session, session.begin():
            decision = await self._begin(session, command, actor_id, "receive")
            if decision.replayed:
                return await _replay(session, command.company_id, decision.response_body)
            repository = GoodsReceiptRepository(session, company_id=command.company_id)
            current = await _required(repository, command.receipt_id)
            _version(current.version, command.expected_version)
            try:
                changed = current.confirm_received(occurred_at=command.occurred_at)
            except ValueError as error:
                raise _validation("Invalid physical receipt transition.", error) from error
            await repository.save(
                changed, actor_id=actor_id, expected_version=command.expected_version
            )
            await record_goods_receipt_event(
                session,
                receipt=changed,
                event_type=GOODS_RECEIPT_RECEIVED,
                metadata=command.metadata,
            )
            await _complete(self._idempotency, session, decision, changed)
            return changed

    async def inspect(self, command: InspectGoodsReceipt, *, actor_id: UUID) -> GoodsReceipt:
        async with self._database.session() as session, session.begin():
            decision = await self._begin(session, command, actor_id, "inspect")
            if decision.replayed:
                return await _replay(session, command.company_id, decision.response_body)
            repository = GoodsReceiptRepository(session, company_id=command.company_id)
            current = await _required(repository, command.receipt_id)
            _version(current.version, command.expected_version)
            items = {item.id: item for item in current.items}
            try:
                results = tuple(
                    QualityInspectionResult.create(
                        item=items[value.receipt_item_id],
                        inspection_id=value.inspection_id,
                        disposition=value.disposition,
                        approved_quantity=value.approved_quantity,
                        rejected_quantity=value.rejected_quantity,
                        quarantine_quantity=value.quarantine_quantity,
                        reason_code=value.reason_code,
                    )
                    for value in command.decisions
                )
                changed = current.apply_inspection_results(results)
            except KeyError as error:
                raise _validation(
                    "Inspection references an unknown receipt item.", error
                ) from error
            except ValueError as error:
                raise _validation("Invalid M17 inspection decision.", error) from error
            await repository.save(
                changed, actor_id=actor_id, expected_version=command.expected_version
            )
            await record_goods_receipt_event(
                session,
                receipt=changed,
                event_type=GOODS_RECEIPT_INSPECTED,
                metadata=command.metadata,
            )
            await _complete(self._idempotency, session, decision, changed)
            return changed

    async def post_to_inventory(
        self, command: PostGoodsReceiptToInventory, *, actor_id: UUID
    ) -> GoodsReceipt:
        async with self._database.session() as session, session.begin():
            decision = await self._begin(session, command, actor_id, "post-to-inventory")
            if decision.replayed:
                return await _replay(session, command.company_id, decision.response_body)
            repository = GoodsReceiptRepository(session, company_id=command.company_id)
            current = await _required(repository, command.receipt_id)
            _version(current.version, command.expected_version)
            confirmations = []
            ledger = InventoryLedgerRepository(session, company_id=command.company_id)
            balances = InventoryBalanceRepository(session, company_id=command.company_id)
            for request in current.posting_requests:
                transaction = InventoryTransaction.create(
                    company_id=command.company_id,
                    transaction_type=InventoryTransactionType.RECEIPT,
                    reference_type="GOODS_RECEIPT",
                    reference_id=current.id,
                    created_by=actor_id,
                )
                posting = InventoryPosting.create(
                    company_id=command.company_id,
                    transaction_id=transaction.id,
                    sequence=1,
                    product_id=request.product_id,
                    warehouse_id=request.warehouse_id,
                    lot_id=await _lot_id(
                        session,
                        company_id=command.company_id,
                        product_id=request.product_id,
                        reference=request.lot_reference,
                    ),
                    state=InventoryState(request.state),
                    quantity_delta=request.quantity,
                )
                await ledger.append(InventoryLedgerEntry(transaction, (posting,)))
                await balances.apply(posting)
                confirmations.append(
                    InventoryPostingConfirmation.create(
                        posting_request_id=request.id,
                        inventory_transaction_id=transaction.id,
                    )
                )
            try:
                changed = current.confirm_inventory_posting(tuple(confirmations))
            except ValueError as error:
                raise _validation("Invalid M5 inventory posting.", error) from error
            await repository.save(
                changed, actor_id=actor_id, expected_version=command.expected_version
            )
            await record_goods_receipt_event(
                session,
                receipt=changed,
                event_type=GOODS_RECEIPT_POSTED,
                metadata=command.metadata,
            )
            await _complete(self._idempotency, session, decision, changed)
            return changed

    async def get(self, company_id: UUID, receipt_id: UUID) -> GoodsReceipt | None:
        async with self._database.session() as session:
            return await GoodsReceiptRepository(session, company_id=company_id).get(receipt_id)

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
    ) -> GoodsReceiptPage:
        async with self._database.session() as session:
            repository = GoodsReceiptRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            values = await repository.list(
                status=status,
                purchase_order_id=purchase_order_id,
                supplier_id=supplier_id,
                created_from=created_from,
                created_to=created_to,
                limit=page_size,
                offset=offset,
            )
            more = await repository.list(
                status=status,
                purchase_order_id=purchase_order_id,
                supplier_id=supplier_id,
                created_from=created_from,
                created_to=created_to,
                limit=1,
                offset=offset + page_size,
            )
            return GoodsReceiptPage(values, page, page_size, bool(more))

    async def _begin(
        self,
        session: AsyncSession,
        command: ReceiveGoodsReceipt | InspectGoodsReceipt | PostGoodsReceiptToInventory,
        actor_id: UUID,
        action: str,
    ) -> IdempotencyDecision:
        return await self._idempotency.begin(
            session,
            scope=_scope(command.company_id, actor_id),
            operation=f"procurement.goods-receipt.{action}",
            key=command.idempotency_key,
            payload=command.payload(),
        )


async def _required(repository: GoodsReceiptRepository, receipt_id: UUID) -> GoodsReceipt:
    value = await repository.get(receipt_id)
    if value is None:
        raise _not_found("Goods receipt")
    return value


async def _replay(
    session: AsyncSession, company_id: UUID, body: dict[str, Any] | None
) -> GoodsReceipt:
    if body is None or "receipt_id" not in body:
        raise RuntimeError("Stored goods receipt replay has no receipt identity.")
    return await _required(
        GoodsReceiptRepository(session, company_id=company_id), UUID(str(body["receipt_id"]))
    )


async def _complete(
    service: IdempotencyService,
    session: AsyncSession,
    decision: IdempotencyDecision,
    receipt: GoodsReceipt,
    status: int = 200,
) -> None:
    await service.complete(
        session,
        decision,
        response_status=status,
        response_body={"receipt_id": str(receipt.id)},
    )


async def _lot_id(
    session: AsyncSession,
    *,
    company_id: UUID,
    product_id: UUID,
    reference: str | None,
) -> UUID | None:
    if reference is None:
        return None
    value = await session.scalar(
        select(InventoryLotModel.id).where(
            InventoryLotModel.company_id == company_id,
            InventoryLotModel.product_id == product_id,
            InventoryLotModel.code == reference,
        )
    )
    if value is None:
        raise _not_found("Inventory lot")
    return value


def _scope(company_id: UUID, actor_id: UUID) -> str:
    return f"procurement-receipt:{company_id}:{actor_id}"


def _version(actual: int, expected: int) -> None:
    if actual != expected:
        raise ApplicationError(
            code="VERSION_CONFLICT",
            message="The resource was changed by another transaction.",
            status_code=409,
        )


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND", message=f"{resource} not found.", status_code=404
    )


def _validation(message: str, error: Exception) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message=message,
        status_code=422,
        details=[ErrorDetail(message=str(error))],
    )


__all__ = ["PostgresGoodsReceiptOperations"]
