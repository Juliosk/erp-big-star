"""Atomic Audit and Outbox effects for M6 purchasing transitions."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.application.purchasing import ProcurementCommandMetadata
from erp.modules.procurement.domain import PurchaseOrder, PurchaseRequisition
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

PURCHASE_APPROVAL_REQUESTED = "PurchaseApprovalRequested"
PURCHASE_ORDER_APPROVED = "PurchaseOrderApproved"
PURCHASE_ORDER_REJECTED = "PurchaseOrderRejected"
PURCHASE_ORDER_CANCELLED = "PurchaseOrderCancelled"


async def record_purchasing_effect(
    session: AsyncSession,
    *,
    before: PurchaseOrder | PurchaseRequisition,
    after: PurchaseOrder | PurchaseRequisition,
    event_type: str,
    actor_id: UUID,
    metadata: ProcurementCommandMetadata,
    causation_id: UUID | None = None,
) -> tuple[UUID, UUID]:
    aggregate_type = (
        "purchase_order" if isinstance(after, PurchaseOrder) else "purchase_requisition"
    )
    before_snapshot = purchasing_snapshot(before)
    after_snapshot = purchasing_snapshot(after)
    audit_id = await AuditService().record(
        session,
        AuditEvent(
            actor_user_id=actor_id,
            company_id=after.company_id,
            branch_id=None,
            module="procurement",
            entity_type=aggregate_type,
            entity_id=after.id,
            operation=event_type,
            request_id=metadata.request_id,
            correlation_id=metadata.correlation_id,
            source_ip=metadata.source_ip,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        ),
    )
    envelope = MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=event_type,
        event_version=1,
        producer_module="procurement",
        producer_domain="procurement",
        aggregate_type=aggregate_type,
        aggregate_id=after.id,
        aggregate_version=after.version,
        company_id=after.company_id,
        branch_id=None,
        correlation_id=metadata.correlation_id,
        request_id=metadata.request_id,
        causation_id=causation_id,
        payload={
            "company_id": str(after.company_id),
            "source_module": "procurement",
            "source_type": aggregate_type.upper(),
            "source_id": str(after.id),
            "status": str(after.status),
            "requested_by": str(_owner(after)),
            "amount": str(after.total_amount) if isinstance(after, PurchaseOrder) else "0.00",
            "currency": after.currency if isinstance(after, PurchaseOrder) else "BRL",
            "aggregate_version": after.version,
        },
    )
    await OutboxService().enqueue(session, envelope)
    return envelope.message_id, audit_id


def _owner(value: PurchaseOrder | PurchaseRequisition) -> UUID:
    return value.buyer_id if isinstance(value, PurchaseOrder) else value.requester_id


def purchasing_snapshot(value: PurchaseOrder | PurchaseRequisition) -> dict[str, object]:
    common: dict[str, object] = {
        "id": str(value.id),
        "company_id": str(value.company_id),
        "number": value.number,
        "status": str(value.status),
        "version": value.version,
    }
    if isinstance(value, PurchaseOrder):
        common.update(
            {
                "supplier_id": str(value.supplier_id),
                "buyer_id": str(value.buyer_id),
                "total_amount": str(value.total_amount),
                "currency": value.currency,
            }
        )
    else:
        common.update(
            {"requester_id": str(value.requester_id), "cost_center_id": str(value.cost_center_id)}
        )
    return common


__all__ = [
    "PURCHASE_APPROVAL_REQUESTED",
    "PURCHASE_ORDER_APPROVED",
    "PURCHASE_ORDER_CANCELLED",
    "PURCHASE_ORDER_REJECTED",
    "purchasing_snapshot",
    "record_purchasing_effect",
]
