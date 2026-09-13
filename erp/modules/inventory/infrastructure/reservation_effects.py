"""Audit and Outbox effects for inventory reservations."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.inventory.application.commands import (
    CommandMetadata,
    InventoryReservationResult,
)
from erp.modules.inventory.domain import InventoryReservation
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


def _snapshot(reservation: InventoryReservation) -> dict[str, object]:
    return {
        "id": str(reservation.id),
        "company_id": str(reservation.company_id),
        "reservation_kind": reservation.reservation_kind,
        "status": reservation.status,
        "reference_type": reservation.reference_type,
        "reference_id": str(reservation.reference_id),
        "expires_at": reservation.expires_at.isoformat()
        if reservation.expires_at is not None
        else None,
        "created_at": reservation.created_at.isoformat(),
        "created_by": str(reservation.created_by),
        "version": reservation.version,
        "allocations": [
            {
                "id": str(allocation.id),
                "product_id": str(allocation.product_id),
                "warehouse_id": str(allocation.warehouse_id),
                "location_id": str(allocation.location_id)
                if allocation.location_id is not None
                else None,
                "lot_id": str(allocation.lot_id) if allocation.lot_id is not None else None,
                "pool_id": str(allocation.pool_id) if allocation.pool_id is not None else None,
                "state": allocation.state,
                "quantity": f"{allocation.quantity.value:.6f}",
            }
            for allocation in reservation.allocations
        ],
    }


class InventoryReservationEffects:
    async def record(
        self,
        session: AsyncSession,
        reservation: InventoryReservation,
        *,
        event_type: str,
        actor_id: UUID,
        metadata: CommandMetadata,
        before: InventoryReservation | None = None,
    ) -> InventoryReservationResult:
        before_snapshot = _snapshot(before) if before is not None else None
        after_snapshot = _snapshot(reservation)
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=reservation.company_id,
                branch_id=None,
                module="inventory",
                entity_type="inventory_reservation",
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
            producer_module="inventory",
            producer_domain="inventory",
            aggregate_type="inventory_reservation",
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
        return InventoryReservationResult(reservation, envelope.message_id, audit_id)


__all__ = ["InventoryReservationEffects"]
