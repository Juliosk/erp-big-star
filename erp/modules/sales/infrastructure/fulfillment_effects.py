"""Atomic Audit and Outbox effects for multichannel fulfillment."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.sales.application.fulfillment import (
    FulfillSalesOrder,
    sales_shipment_snapshot,
)
from erp.modules.sales.domain import ChannelOrderStatus, SalesShipment
from erp.modules.wms.contracts import OutboundShipmentReference
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

MARKETPLACE_FULFILLMENT_SYNC_REQUESTED = "MarketplaceFulfillmentSyncRequested"


class SalesFulfillmentEffects:
    async def record(
        self,
        session: AsyncSession,
        command: FulfillSalesOrder,
        shipment: SalesShipment,
        wms_shipment: OutboundShipmentReference,
        *,
        actor_id: UUID,
    ) -> tuple[UUID, UUID]:
        snapshot = {
            **sales_shipment_snapshot(shipment),
            "target_channel_status": ChannelOrderStatus.SHIPPED,
            "wms_shipment": wms_shipment.to_dict(),
        }
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=command.company_id,
                branch_id=None,
                module="sales",
                entity_type="sales_shipment",
                entity_id=shipment.id,
                operation=MARKETPLACE_FULFILLMENT_SYNC_REQUESTED,
                request_id=command.metadata.request_id,
                correlation_id=command.metadata.correlation_id,
                source_ip=command.metadata.source_ip,
                before_snapshot=None,
                after_snapshot=snapshot,
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.ASYNC_REQUEST,
            message_type=MARKETPLACE_FULFILLMENT_SYNC_REQUESTED,
            event_version=1,
            producer_module="sales",
            producer_domain="sales",
            aggregate_type="sales_shipment",
            aggregate_id=shipment.id,
            aggregate_version=shipment.version,
            company_id=shipment.company_id,
            branch_id=None,
            correlation_id=command.metadata.correlation_id,
            causation_id=None,
            request_id=command.metadata.request_id,
            payload=snapshot,
        )
        await OutboxService().enqueue(session, envelope)
        return envelope.message_id, audit_id


__all__ = [
    "MARKETPLACE_FULFILLMENT_SYNC_REQUESTED",
    "SalesFulfillmentEffects",
]
