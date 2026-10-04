"""Transactional domain events and idempotent lifecycle consumer for M6 receipts."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.application.purchasing import ProcurementCommandMetadata
from erp.modules.procurement.domain import GoodsReceipt
from erp.platform.database import Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

GOODS_RECEIPT_CREATED = "GoodsReceiptCreated"
GOODS_RECEIPT_RECEIVED = "GoodsReceiptReceived"
GOODS_RECEIPT_INSPECTED = "GoodsReceiptInspected"
GOODS_RECEIPT_POSTED = "GoodsReceiptPosted"
GOODS_RECEIPT_EVENTS = frozenset(
    {
        GOODS_RECEIPT_CREATED,
        GOODS_RECEIPT_RECEIVED,
        GOODS_RECEIPT_INSPECTED,
        GOODS_RECEIPT_POSTED,
    }
)
GOODS_RECEIPT_LIFECYCLE_CONSUMER = "procurement.goods-receipt-lifecycle.v1"


async def record_goods_receipt_event(
    session: AsyncSession,
    *,
    receipt: GoodsReceipt,
    event_type: str,
    metadata: ProcurementCommandMetadata,
    causation_id: UUID | None = None,
) -> MessageEnvelope:
    """Stage a complete receipt event without taking transaction ownership."""
    if event_type not in GOODS_RECEIPT_EVENTS:
        raise ValueError("Unsupported goods receipt event type.")
    envelope = MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=event_type,
        event_version=1,
        producer_module="procurement",
        producer_domain="procurement",
        aggregate_type="goods_receipt",
        aggregate_id=receipt.id,
        aggregate_version=receipt.version,
        company_id=receipt.company_id,
        branch_id=None,
        correlation_id=metadata.correlation_id,
        request_id=metadata.request_id,
        causation_id=causation_id,
        payload={
            "receipt_id": str(receipt.id),
            "purchase_order_id": str(receipt.purchase_order_id),
            "supplier_id": str(receipt.supplier_id),
            "warehouse_id": str(receipt.warehouse_id),
            "status": receipt.status.value,
            "item_count": len(receipt.items),
            "inspection_count": len(receipt.inspection_results),
            "inventory_transaction_ids": [
                str(value) for value in receipt.inventory_transaction_ids
            ],
        },
    )
    await OutboxService().enqueue(session, envelope)
    return envelope


class GoodsReceiptLifecycleConsumer:
    """Validate and acknowledge receipt lifecycle events exactly once via Inbox."""

    def __init__(self, database: Database, inbox: InboxService | None = None) -> None:
        self._database = database
        self._inbox = inbox or InboxService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        if (
            envelope.message_type not in GOODS_RECEIPT_EVENTS
            or envelope.event_version != 1
            or envelope.producer_module != "procurement"
            or envelope.producer_domain != "procurement"
            or envelope.aggregate_type != "goods_receipt"
            or envelope.aggregate_version is None
            or envelope.company_id is None
        ):
            raise ValueError("Unsupported goods receipt lifecycle envelope.")

        async def effect(_session: AsyncSession, message: MessageEnvelope) -> None:
            if message.payload.get("receipt_id") != str(message.aggregate_id):
                raise ValueError("Goods receipt event identity does not match its aggregate.")
            if not message.payload.get("status"):
                raise ValueError("Goods receipt event requires a status.")

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=GOODS_RECEIPT_LIFECYCLE_CONSUMER,
                envelope=envelope,
                effect=effect,
            )


__all__ = [
    "GOODS_RECEIPT_CREATED",
    "GOODS_RECEIPT_EVENTS",
    "GOODS_RECEIPT_INSPECTED",
    "GOODS_RECEIPT_LIFECYCLE_CONSUMER",
    "GOODS_RECEIPT_POSTED",
    "GOODS_RECEIPT_RECEIVED",
    "GoodsReceiptLifecycleConsumer",
    "record_goods_receipt_event",
]
