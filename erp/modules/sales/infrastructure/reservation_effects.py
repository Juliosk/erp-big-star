"""Sales-owned Audit and Outbox effects for order reservation transitions."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.sales.application.lifecycle import CommandMetadata
from erp.modules.sales.domain import SalesOrderReservation
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


def reservation_snapshot(reservation: SalesOrderReservation) -> dict[str, object]:
    return {
        "id": str(reservation.id),
        "company_id": str(reservation.company_id),
        "order_id": str(reservation.order_id),
        "inventory_reservation_id": str(reservation.inventory_reservation_id)
        if reservation.inventory_reservation_id
        else None,
        "hold_expires_at": reservation.hold_expires_at.isoformat()
        if reservation.hold_expires_at
        else None,
        "status": reservation.status,
        "order_version": reservation.order_version,
        "version": reservation.version,
        "lines": [
            {
                "order_item_id": str(line.order_item_id),
                "product_id": str(line.product_id),
                "quantity": str(line.quantity),
                "pricing_snapshot_id": str(line.pricing_snapshot_id)
                if line.pricing_snapshot_id
                else None,
            }
            for line in reservation.lines
        ],
    }


class SalesOrderReservationEffects:
    async def record(
        self,
        session: AsyncSession,
        reservation: SalesOrderReservation,
        *,
        event_type: str,
        actor_id: UUID,
        metadata: CommandMetadata,
        before: SalesOrderReservation | None = None,
    ) -> tuple[UUID, UUID]:
        before_snapshot = reservation_snapshot(before) if before else None
        after_snapshot = reservation_snapshot(reservation)
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=reservation.company_id,
                branch_id=None,
                module="sales",
                entity_type="sales_order_reservation",
                entity_id=reservation.id,
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
            producer_module="sales",
            producer_domain="sales",
            aggregate_type="sales_order_reservation",
            aggregate_id=reservation.id,
            aggregate_version=reservation.version,
            company_id=reservation.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            request_id=metadata.request_id,
            causation_id=None,
            payload=after_snapshot,
        )
        await OutboxService().enqueue(session, envelope)
        return envelope.message_id, audit_id


__all__ = ["SalesOrderReservationEffects", "reservation_snapshot"]
