"""Atomic Audit and Outbox effects for multichannel order ingestion."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.inventory.contracts import InventoryReservationReference
from erp.modules.sales.application.lifecycle import CommandMetadata
from erp.modules.sales.domain import ChannelFee, MultichannelSalesOrder
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


class MultichannelOrderEffects:
    async def record(
        self,
        session: AsyncSession,
        order: MultichannelSalesOrder,
        reservation: InventoryReservationReference,
        *,
        fees: tuple[ChannelFee, ...],
        actor_id: UUID,
        metadata: CommandMetadata,
    ) -> tuple[UUID, UUID]:
        payload = multichannel_order_snapshot(order, reservation, fees=fees)
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=order.snapshot.reference.company_id,
                branch_id=None,
                module="sales",
                entity_type="multichannel_sales_order",
                entity_id=order.id,
                operation="INGEST",
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                source_ip=metadata.source_ip,
                before_snapshot=None,
                after_snapshot=payload,
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type="MarketplaceOrderApproved",
            event_version=1,
            producer_module="sales",
            producer_domain="sales",
            aggregate_type="multichannel_sales_order",
            aggregate_id=order.id,
            aggregate_version=order.record_version,
            company_id=order.snapshot.reference.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            causation_id=None,
            request_id=metadata.request_id,
            payload=payload,
        )
        await OutboxService().enqueue(session, envelope)
        return envelope.message_id, audit_id


def multichannel_order_snapshot(
    order: MultichannelSalesOrder,
    reservation: InventoryReservationReference,
    *,
    fees: tuple[ChannelFee, ...],
) -> dict[str, object]:
    snapshot = order.snapshot
    return {
        "id": str(order.id),
        "company_id": str(snapshot.reference.company_id),
        "channel_config_id": str(order.channel_config_id),
        "account_id": str(snapshot.reference.account_id),
        "marketplace": snapshot.reference.marketplace,
        "external_order_id": snapshot.reference.external_order_id,
        "status": snapshot.status,
        "currency": snapshot.currency,
        "merchandise_amount": str(snapshot.merchandise_amount),
        "freight_amount": str(snapshot.freight_amount),
        "discount_amount": str(snapshot.discount_amount),
        "total_amount": str(snapshot.total_amount),
        "channel_fees": [{"code": fee.code, "amount": str(fee.amount)} for fee in fees],
        "inventory_reservation_id": str(reservation.id),
        "items": [
            {
                "external_item_id": item.external_item_id,
                "product_id": str(item.mapping.product_id),
                "external_sku": item.mapping.external_sku,
                "quantity": str(item.quantity),
                "unit_price": str(item.unit_price),
            }
            for item in snapshot.items
        ],
    }


__all__ = ["MultichannelOrderEffects", "multichannel_order_snapshot"]
