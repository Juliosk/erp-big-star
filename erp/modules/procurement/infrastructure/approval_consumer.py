"""Idempotent M22 approval decision consumer owned by M6 Procurement."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.application.purchasing import (
    ProcurementCommandMetadata,
    enforce_separation_of_duties,
)
from erp.modules.procurement.domain import PurchaseOrderStatus
from erp.modules.procurement.infrastructure.purchasing_effects import (
    PURCHASE_ORDER_APPROVED,
    PURCHASE_ORDER_REJECTED,
    record_purchasing_effect,
)
from erp.modules.procurement.infrastructure.purchasing_repository import PurchaseOrderRepository
from erp.platform.database import Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope

APPROVAL_DECISION_MADE = "ApprovalDecisionMade"
PROCUREMENT_APPROVAL_CONSUMER = "procurement.approval-decision.v1"


class ProcurementApprovalDecisionConsumer:
    def __init__(self, database: Database, inbox: InboxService | None = None) -> None:
        self._database = database
        self._inbox = inbox or InboxService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        if (
            envelope.message_type != APPROVAL_DECISION_MADE
            or envelope.event_version != 1
            or envelope.producer_module != "workflow"
            or envelope.producer_domain != "workflow"
            or envelope.company_id is None
        ):
            raise ValueError("Unsupported workflow approval decision envelope.")

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            if (
                message.payload.get("source_module") != "procurement"
                or message.payload.get("source_type") != "PURCHASE_ORDER"
            ):
                raise ValueError("Approval decision does not target an M6 purchase order.")
            order_id = _uuid(message, "source_id")
            actor_id = _uuid(message, "decided_by")
            repository = PurchaseOrderRepository(session, company_id=message.company_id)  # type: ignore[arg-type]
            current = await repository.get(order_id)
            if current is None:
                raise ValueError("Purchase order targeted by approval was not found.")
            if current.buyer_id == actor_id:
                enforce_separation_of_duties(owner_id=current.buyer_id, approver_id=actor_id)
            if current.status in {PurchaseOrderStatus.APPROVED, PurchaseOrderStatus.REJECTED}:
                return
            if current.status is not PurchaseOrderStatus.PENDING_APPROVAL:
                raise ValueError("Purchase order is not pending approval.")
            decision = message.payload.get("decision")
            if decision == "APPROVED":
                changed, event_type = current.approve(), PURCHASE_ORDER_APPROVED
            elif decision == "REJECTED":
                changed, event_type = current.reject(), PURCHASE_ORDER_REJECTED
            else:
                raise ValueError("Approval decision must be APPROVED or REJECTED.")
            changed = await repository.save(
                changed, actor_id=actor_id, expected_version=current.version
            )
            await record_purchasing_effect(
                session,
                before=current,
                after=changed,
                event_type=event_type,
                actor_id=actor_id,
                metadata=ProcurementCommandMetadata(
                    request_id=message.request_id,
                    correlation_id=message.correlation_id,
                ),
                causation_id=message.message_id,
            )

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=PROCUREMENT_APPROVAL_CONSUMER,
                envelope=envelope,
                effect=effect,
            )


def _uuid(message: MessageEnvelope, field: str) -> UUID:
    try:
        return UUID(str(message.payload.get(field)))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Approval decision requires a valid {field}.") from error


__all__ = [
    "APPROVAL_DECISION_MADE",
    "PROCUREMENT_APPROVAL_CONSUMER",
    "ProcurementApprovalDecisionConsumer",
]
