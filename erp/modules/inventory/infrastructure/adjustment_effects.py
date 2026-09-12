"""Audit and Outbox effects for inventory adjustments."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.inventory.application.commands import (
    CommandMetadata,
    InventoryAdjustmentResult,
)
from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.domain import InventoryBalance
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


class InventoryAdjustmentEffects:
    async def record(
        self,
        session: AsyncSession,
        entry: InventoryLedgerEntry,
        balances: tuple[InventoryBalance, ...],
        *,
        actor_id: UUID,
        metadata: CommandMetadata,
        reason: str,
    ) -> InventoryAdjustmentResult:
        after_snapshot: dict[str, object] = {
            "transaction_id": str(entry.transaction.id),
            "reason": reason,
            "postings": [
                {
                    "id": str(posting.id),
                    "product_id": str(posting.product_id),
                    "warehouse_id": str(posting.warehouse_id),
                    "location_id": str(posting.location_id)
                    if posting.location_id is not None
                    else None,
                    "lot_id": str(posting.lot_id) if posting.lot_id is not None else None,
                    "pool_id": str(posting.pool_id) if posting.pool_id is not None else None,
                    "state": posting.state,
                    "quantity_delta": f"{posting.quantity_delta:.6f}",
                }
                for posting in entry.postings
            ],
            "balances": [
                {
                    "id": str(balance.id),
                    "product_id": str(balance.product_id),
                    "warehouse_id": str(balance.warehouse_id),
                    "location_id": str(balance.location_id)
                    if balance.location_id is not None
                    else None,
                    "lot_id": str(balance.lot_id) if balance.lot_id is not None else None,
                    "pool_id": str(balance.pool_id) if balance.pool_id is not None else None,
                    "state": balance.state,
                    "quantity": f"{balance.quantity.value:.6f}",
                    "version": balance.version,
                }
                for balance in balances
            ],
        }
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=entry.company_id,
                branch_id=None,
                module="inventory",
                entity_type="inventory_adjustment",
                entity_id=entry.transaction.id,
                operation="InventoryAdjusted",
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                source_ip=metadata.source_ip,
                before_snapshot=None,
                after_snapshot=after_snapshot,
                reason_code=reason,
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type="InventoryAdjusted",
            event_version=1,
            producer_module="inventory",
            producer_domain="inventory",
            aggregate_type="inventory_adjustment",
            aggregate_id=entry.transaction.id,
            aggregate_version=1,
            company_id=entry.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            request_id=metadata.request_id,
            causation_id=None,
            payload=after_snapshot,
        )
        await OutboxService().enqueue(session, envelope)
        return InventoryAdjustmentResult(
            entry.transaction.id, balances, envelope.message_id, audit_id
        )


__all__ = ["InventoryAdjustmentEffects"]
