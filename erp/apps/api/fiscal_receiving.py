"""Atomic composition of M11 inbound fiscal, M6 receipt and M5 inventory."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.fiscal.application.reconciliation import (
    FiscalReceivingReconciliation,
    ReconcileFiscalReceiving,
    ReconciliationIssue,
    ReconciliationIssueKind,
    ReconciliationResult,
    ReconciliationStatus,
)
from erp.modules.fiscal.infrastructure import (
    FiscalReceivingReconciliationRepository,
    InboundFiscalDocumentModel,
    InboundFiscalDocumentRepository,
)
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
from erp.modules.procurement.application.purchasing import ProcurementCommandMetadata
from erp.modules.procurement.domain import (
    GoodsReceipt,
    GoodsReceiptStatus,
    InspectionDisposition,
    InventoryPostingConfirmation,
)
from erp.modules.procurement.infrastructure.goods_receipt_events import (
    GOODS_RECEIPT_POSTED,
    record_goods_receipt_event,
)
from erp.modules.procurement.infrastructure.goods_receipt_model import GoodsReceiptModel
from erp.modules.procurement.infrastructure.goods_receipt_repository import (
    GoodsReceiptRepository,
)
from erp.modules.procurement.infrastructure.purchasing_repository import PurchaseOrderRepository
from erp.modules.procurement.infrastructure.supplier_model import SupplierModel
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyDecision, IdempotencyService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

FISCAL_RECEIVING_RECONCILED = "FiscalReceivingReconciled"


class PostgresFiscalReceivingReconciliation:
    """Own the cross-module transaction while each repository stays tenant-bound."""

    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def reconcile(
        self, command: ReconcileFiscalReceiving, *, actor_id: UUID
    ) -> ReconciliationResult:
        async with self._database.session() as session, session.begin():
            decision = await self._begin(session, command, actor_id)
            repository = FiscalReceivingReconciliationRepository(
                session, company_id=command.company_id
            )
            if decision.replayed:
                return ReconciliationResult(
                    await _replayed(repository, command.inbound_fiscal_document_id), True
                )
            await _lock_roots(session, command)
            inbound = await InboundFiscalDocumentRepository(
                session, company_id=command.company_id
            ).get(command.inbound_fiscal_document_id)
            receipt_repository = GoodsReceiptRepository(session, company_id=command.company_id)
            receipt = await receipt_repository.get(command.goods_receipt_id)
            if inbound is None or receipt is None:
                raise _not_found()
            if inbound.version != command.expected_inbound_version:
                raise ApplicationError(
                    code="VERSION_CONFLICT",
                    message="The inbound fiscal document changed in another transaction.",
                    status_code=409,
                )
            if receipt.status is not GoodsReceiptStatus.INSPECTED:
                raise ApplicationError(
                    code="GOODS_RECEIPT_NOT_INSPECTED",
                    message="Fiscal reconciliation requires an inspected goods receipt.",
                    status_code=409,
                )
            order = await PurchaseOrderRepository(session, company_id=command.company_id).get(
                receipt.purchase_order_id
            )
            if order is None:
                raise _not_found()
            supplier_tax_id = await session.scalar(
                select(SupplierModel.identity_value).where(
                    SupplierModel.company_id == command.company_id,
                    SupplierModel.id == receipt.supplier_id,
                )
            )
            issues = _issues(
                inbound=inbound,
                receipt=receipt,
                order=order,
                supplier_tax_id=supplier_tax_id,
                command=command,
            )
            transaction_ids: tuple[UUID, ...] = ()
            changed_receipt = receipt
            status = ReconciliationStatus.DIVERGENT
            if not issues:
                changed_receipt, transaction_ids = await _post_available(session, receipt, actor_id)
                await receipt_repository.save(
                    changed_receipt,
                    actor_id=actor_id,
                    expected_version=receipt.version,
                )
                status = ReconciliationStatus.POSTED
            reconciliation = FiscalReceivingReconciliation(
                id=uuid4(),
                company_id=command.company_id,
                inbound_fiscal_document_id=inbound.id,
                goods_receipt_id=receipt.id,
                purchase_order_id=receipt.purchase_order_id,
                status=status,
                issues=issues,
                financial_blocked=any(value.kind.blocks_financial for value in issues),
                physical_pending=any(value.kind.blocks_physical for value in issues),
                inventory_transaction_ids=transaction_ids,
                version=1,
                reconciled_at=datetime.now(UTC),
            )
            await repository.add(reconciliation, actor_id=actor_id)
            await _effects(session, reconciliation, actor_id, command)
            if status is ReconciliationStatus.POSTED:
                await record_goods_receipt_event(
                    session,
                    receipt=changed_receipt,
                    event_type=GOODS_RECEIPT_POSTED,
                    metadata=ProcurementCommandMetadata(
                        request_id=command.metadata.request_id,
                        correlation_id=command.metadata.correlation_id,
                        source_ip=command.metadata.source_ip,
                    ),
                )
            await self._idempotency.complete(
                session,
                decision,
                response_status=200,
                response_body={"reconciliation_id": str(reconciliation.id)},
            )
            return ReconciliationResult(reconciliation)

    async def get(
        self, company_id: UUID, inbound_document_id: UUID
    ) -> FiscalReceivingReconciliation | None:
        async with self._database.session() as session:
            return await FiscalReceivingReconciliationRepository(
                session, company_id=company_id
            ).get_by_inbound(inbound_document_id)

    async def _begin(
        self, session: AsyncSession, command: ReconcileFiscalReceiving, actor_id: UUID
    ) -> IdempotencyDecision:
        return await self._idempotency.begin(
            session,
            scope=f"fiscal-receiving:{command.company_id}:{actor_id}",
            operation=f"reconcile:{command.inbound_fiscal_document_id}",
            key=command.idempotency_key,
            payload={
                "company_id": str(command.company_id),
                "inbound_fiscal_document_id": str(command.inbound_fiscal_document_id),
                "goods_receipt_id": str(command.goods_receipt_id),
                "expected_inbound_version": command.expected_inbound_version,
                "price_tolerance": str(command.price_tolerance),
                "line_mappings": [
                    {
                        "inbound_line_number": value.inbound_line_number,
                        "receipt_item_id": str(value.receipt_item_id),
                    }
                    for value in command.line_mappings
                ],
            },
        )


async def _lock_roots(session: AsyncSession, command: ReconcileFiscalReceiving) -> None:
    inbound_id = await session.scalar(
        select(InboundFiscalDocumentModel.id)
        .where(
            InboundFiscalDocumentModel.company_id == command.company_id,
            InboundFiscalDocumentModel.id == command.inbound_fiscal_document_id,
        )
        .with_for_update()
    )
    receipt_id = await session.scalar(
        select(GoodsReceiptModel.id)
        .where(
            GoodsReceiptModel.company_id == command.company_id,
            GoodsReceiptModel.id == command.goods_receipt_id,
        )
        .with_for_update()
    )
    if inbound_id is None or receipt_id is None:
        raise _not_found()


def _issues(
    *,
    inbound: Any,
    receipt: GoodsReceipt,
    order: Any,
    supplier_tax_id: str | None,
    command: ReconcileFiscalReceiving,
) -> tuple[ReconciliationIssue, ...]:
    issues: list[ReconciliationIssue] = []
    if receipt.purchase_order_id != order.id:
        raise ApplicationError(
            code="RECONCILIATION_ORDER_MISMATCH",
            message="The goods receipt and purchase order do not match.",
            status_code=409,
        )
    if supplier_tax_id != inbound.supplier.tax_id:
        issues.append(
            ReconciliationIssue(
                ReconciliationIssueKind.SUPPLIER_MISMATCH,
                "Supplier fiscal identity differs from the inbound NF-e.",
                expected=supplier_tax_id,
                actual=inbound.supplier.tax_id,
            )
        )
    inbound_lines = {value.line_number: value for value in inbound.items}
    receipt_items = {value.id: value for value in receipt.items}
    mapped_lines = {value.inbound_line_number for value in command.line_mappings}
    mapped_items = {value.receipt_item_id for value in command.line_mappings}
    if (
        len(mapped_lines) != len(command.line_mappings)
        or len(mapped_items) != len(command.line_mappings)
        or mapped_lines != set(inbound_lines)
        or mapped_items != set(receipt_items)
    ):
        issues.append(
            ReconciliationIssue(
                ReconciliationIssueKind.LINE_MAPPING_MISMATCH,
                "Mappings must cover every fiscal and physical line exactly once.",
            )
        )
        return tuple(issues)
    order_items = {value.id: value for value in order.items}
    inspections = {value.receipt_item_id: value for value in receipt.inspection_results}
    for mapping in command.line_mappings:
        fiscal_line = inbound_lines[mapping.inbound_line_number]
        physical_line = receipt_items[mapping.receipt_item_id]
        inspection = inspections[physical_line.id]
        order_line = order_items[physical_line.purchase_order_item_id]
        if fiscal_line.quantity != inspection.approved_quantity:
            issues.append(
                _line_issue(
                    ReconciliationIssueKind.QUANTITY_MISMATCH,
                    "Approved physical quantity differs from the NF-e.",
                    mapping,
                    inspection.approved_quantity,
                    fiscal_line.quantity,
                )
            )
        if abs(fiscal_line.unit_price - order_line.unit_price) > command.price_tolerance:
            issues.append(
                _line_issue(
                    ReconciliationIssueKind.UNIT_PRICE_MISMATCH,
                    "NF-e unit price differs from the purchase order.",
                    mapping,
                    order_line.unit_price,
                    fiscal_line.unit_price,
                )
            )
        if not physical_line.specification_conforms:
            issues.append(
                _line_issue(
                    ReconciliationIssueKind.SPECIFICATION_MISMATCH,
                    "Physical specification does not conform to the purchase order.",
                    mapping,
                )
            )
        if inspection.disposition is not InspectionDisposition.APPROVE:
            issues.append(
                _line_issue(
                    ReconciliationIssueKind.INSPECTION_NOT_APPROVED,
                    "M17 inspection did not fully approve the physical line.",
                    mapping,
                    "APPROVE",
                    inspection.disposition.value,
                )
            )
    expected_products = sum(
        (
            order_items[receipt_items[value.receipt_item_id].purchase_order_item_id].unit_price
            * inbound_lines[value.inbound_line_number].quantity
            for value in command.line_mappings
        ),
        Decimal("0"),
    )
    if abs(inbound.products_amount - expected_products) > command.price_tolerance:
        issues.append(
            ReconciliationIssue(
                ReconciliationIssueKind.FISCAL_TOTAL_MISMATCH,
                "NF-e product total differs from the purchase order valuation.",
                expected=str(expected_products),
                actual=str(inbound.products_amount),
            )
        )
    return tuple(issues)


def _line_issue(
    kind: ReconciliationIssueKind,
    message: str,
    mapping: Any,
    expected: object | None = None,
    actual: object | None = None,
) -> ReconciliationIssue:
    return ReconciliationIssue(
        kind,
        message,
        mapping.inbound_line_number,
        mapping.receipt_item_id,
        None if expected is None else str(expected),
        None if actual is None else str(actual),
    )


async def _post_available(
    session: AsyncSession, receipt: GoodsReceipt, actor_id: UUID
) -> tuple[GoodsReceipt, tuple[UUID, ...]]:
    requests = tuple(
        value for value in receipt.posting_requests if value.state.value == "AVAILABLE"
    )
    if len(requests) != len(receipt.items):
        raise ApplicationError(
            code="RECONCILIATION_POSTING_INCOMPLETE",
            message="Every reconciled receipt item must have one AVAILABLE posting.",
            status_code=409,
        )
    ledger = InventoryLedgerRepository(session, company_id=receipt.company_id)
    balances = InventoryBalanceRepository(session, company_id=receipt.company_id)
    confirmations = []
    for request in requests:
        transaction = InventoryTransaction.create(
            company_id=receipt.company_id,
            transaction_type=InventoryTransactionType.RECEIPT,
            reference_type="FISCAL_RECONCILIATION",
            reference_id=receipt.id,
            created_by=actor_id,
        )
        posting = InventoryPosting.create(
            company_id=receipt.company_id,
            transaction_id=transaction.id,
            sequence=1,
            product_id=request.product_id,
            warehouse_id=request.warehouse_id,
            lot_id=await _lot_id(
                session,
                company_id=receipt.company_id,
                product_id=request.product_id,
                reference=request.lot_reference,
            ),
            state=InventoryState.AVAILABLE,
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
    changed = receipt.confirm_inventory_posting(tuple(confirmations))
    return changed, changed.inventory_transaction_ids


async def _lot_id(
    session: AsyncSession, *, company_id: UUID, product_id: UUID, reference: str | None
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
        raise ApplicationError(
            code="RESOURCE_NOT_FOUND", message="Inventory lot not found.", status_code=404
        )
    return value


async def _effects(
    session: AsyncSession,
    value: FiscalReceivingReconciliation,
    actor_id: UUID,
    command: ReconcileFiscalReceiving,
) -> None:
    snapshot: dict[str, object] = {
        "status": value.status.value,
        "financial_blocked": value.financial_blocked,
        "physical_pending": value.physical_pending,
        "issue_count": len(value.issues),
        "inventory_transaction_ids": [str(item) for item in value.inventory_transaction_ids],
    }
    await AuditService().record(
        session,
        AuditEvent(
            actor_user_id=actor_id,
            company_id=value.company_id,
            branch_id=None,
            module="fiscal",
            entity_type="fiscal_receiving_reconciliation",
            entity_id=value.id,
            operation=FISCAL_RECEIVING_RECONCILED,
            request_id=command.metadata.request_id,
            correlation_id=command.metadata.correlation_id,
            source_ip=command.metadata.source_ip,
            after_snapshot=snapshot,
        ),
    )
    envelope = MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=FISCAL_RECEIVING_RECONCILED,
        event_version=1,
        producer_module="fiscal",
        producer_domain="fiscal",
        aggregate_type="fiscal_receiving_reconciliation",
        aggregate_id=value.id,
        aggregate_version=value.version,
        company_id=value.company_id,
        branch_id=None,
        correlation_id=command.metadata.correlation_id,
        request_id=command.metadata.request_id,
        causation_id=None,
        payload={
            "reconciliation_id": str(value.id),
            "inbound_fiscal_document_id": str(value.inbound_fiscal_document_id),
            "goods_receipt_id": str(value.goods_receipt_id),
            "purchase_order_id": str(value.purchase_order_id),
            **snapshot,
        },
    )
    await OutboxService().enqueue(session, envelope)


async def _replayed(
    repository: FiscalReceivingReconciliationRepository, inbound_id: UUID
) -> FiscalReceivingReconciliation:
    value = await repository.get_by_inbound(inbound_id)
    if value is None:
        raise RuntimeError("Idempotent reconciliation references a missing report.")
    return value


def _not_found() -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND",
        message="Inbound fiscal document or goods receipt not found.",
        status_code=404,
    )


__all__ = ["FISCAL_RECEIVING_RECONCILED", "PostgresFiscalReceivingReconciliation"]
