"""Transactional Audit and Outbox effects for confirmed physical putaway."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.contracts import InventoryBalanceReference
from erp.modules.wms.application.putaway import (
    ExecutePutaway,
    putaway_balance_snapshot,
    putaway_bin_snapshot,
)
from erp.modules.wms.domain import WarehouseBin
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

WMS_PUTAWAY_COMPLETED = "WmsPutawayCompleted"


class WmsPutawayEffects:
    async def record(
        self,
        session: AsyncSession,
        command: ExecutePutaway,
        entry: InventoryLedgerEntry,
        before: WarehouseBin,
        after: WarehouseBin,
        source_balance: InventoryBalanceReference,
        destination_balance: InventoryBalanceReference,
        *,
        actor_id: UUID,
    ) -> tuple[UUID, UUID]:
        before_snapshot = putaway_bin_snapshot(before)
        after_snapshot = {
            **putaway_bin_snapshot(after),
            "inventory_transaction_id": str(entry.transaction.id),
            "source_type": command.source_type,
            "source_id": str(command.source_id),
            "product_id": str(command.product_id),
            "quantity": str(command.quantity),
            "lot_id": str(command.lot_id) if command.lot_id else None,
            "pool_id": str(command.pool_id) if command.pool_id else None,
            "source_balance": putaway_balance_snapshot(source_balance),
            "destination_balance": putaway_balance_snapshot(destination_balance),
        }
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=command.company_id,
                branch_id=None,
                module="wms",
                entity_type="wms_bin",
                entity_id=after.inventory_location_id,
                operation=WMS_PUTAWAY_COMPLETED,
                request_id=command.metadata.request_id,
                correlation_id=command.metadata.correlation_id,
                source_ip=command.metadata.source_ip,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=WMS_PUTAWAY_COMPLETED,
            event_version=1,
            producer_module="wms",
            producer_domain="wms",
            aggregate_type="wms_putaway",
            aggregate_id=entry.transaction.id,
            aggregate_version=after.version,
            company_id=command.company_id,
            branch_id=None,
            correlation_id=command.metadata.correlation_id,
            causation_id=None,
            request_id=command.metadata.request_id,
            payload=after_snapshot,
        )
        await OutboxService().enqueue(session, envelope)
        return envelope.message_id, audit_id


__all__ = ["WMS_PUTAWAY_COMPLETED", "WmsPutawayEffects"]
