"""Audit and Outbox effects staged by M10 WMS commands."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.wms.application.waves import (
    CommandMetadata,
    PickingWaveDetail,
    WmsCommandResult,
    picking_wave_detail_snapshot,
)
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

PICKING_WAVE_RELEASED = "PickingWaveReleased"


class WmsEffects:
    """Persist observable WMS side effects in the business transaction."""

    async def record_wave_release(
        self,
        session: AsyncSession,
        detail: PickingWaveDetail,
        *,
        actor_id: UUID,
        metadata: CommandMetadata,
        before: PickingWaveDetail,
    ) -> WmsCommandResult:
        before_snapshot = picking_wave_detail_snapshot(before)
        after_snapshot = picking_wave_detail_snapshot(detail)
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=detail.wave.company_id,
                branch_id=None,
                module="wms",
                entity_type="picking_wave",
                entity_id=detail.wave.id,
                operation=PICKING_WAVE_RELEASED,
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                source_ip=metadata.source_ip,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=PICKING_WAVE_RELEASED,
            event_version=1,
            producer_module="wms",
            producer_domain="wms",
            aggregate_type="picking_wave",
            aggregate_id=detail.wave.id,
            aggregate_version=detail.wave.version,
            company_id=detail.wave.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            request_id=metadata.request_id,
            causation_id=None,
            payload={
                "company_id": str(detail.wave.company_id),
                "picking_wave_id": str(detail.wave.id),
                "code": detail.wave.code,
                "status": detail.wave.status,
                "released_at": (
                    detail.wave.released_at.isoformat()
                    if detail.wave.released_at is not None
                    else None
                ),
                "released_by": (
                    str(detail.wave.released_by)
                    if detail.wave.released_by is not None
                    else None
                ),
                "tasks_count": len(detail.tasks),
            },
        )
        await OutboxService().enqueue(session, envelope)
        return WmsCommandResult(detail, envelope.message_id, audit_id)


__all__ = ["PICKING_WAVE_RELEASED", "WmsEffects"]
