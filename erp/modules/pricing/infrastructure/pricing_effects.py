"""Audit and Outbox effects staged by M9 Pricing commands."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.pricing.application.commands import (
    CommandMetadata,
    PricingCommandResult,
    price_list_version_snapshot,
)
from erp.modules.pricing.domain import PriceListVersion
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

PRICE_LIST_VERSION_ACTIVATED = "PriceListVersionActivated"


class PricingEffects:
    """Persist observable side effects in the same transaction as pricing changes."""

    async def record_version_activation(
        self,
        session: AsyncSession,
        activated: PriceListVersion,
        *,
        actor_id: UUID,
        metadata: CommandMetadata,
        before: PriceListVersion,
        superseded: PriceListVersion | None,
    ) -> PricingCommandResult:
        after_snapshot = price_list_version_snapshot(activated)
        if superseded is not None:
            after_snapshot["superseded_version_id"] = str(superseded.id)
            after_snapshot["superseded_version_number"] = superseded.version_number
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=activated.company_id,
                branch_id=None,
                module="pricing",
                entity_type="price_list_version",
                entity_id=activated.id,
                operation=PRICE_LIST_VERSION_ACTIVATED,
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                source_ip=metadata.source_ip,
                before_snapshot=price_list_version_snapshot(before),
                after_snapshot=after_snapshot,
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=PRICE_LIST_VERSION_ACTIVATED,
            event_version=1,
            producer_module="pricing",
            producer_domain="pricing",
            aggregate_type="price_list_version",
            aggregate_id=activated.id,
            aggregate_version=activated.version,
            company_id=activated.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            causation_id=None,
            request_id=metadata.request_id,
            payload={
                "company_id": str(activated.company_id),
                "price_list_id": str(activated.price_list_id),
                "price_list_version_id": str(activated.id),
                "version_number": activated.version_number,
                "activated_at": (
                    activated.activated_at.isoformat()
                    if activated.activated_at is not None
                    else None
                ),
                "items_count": len(activated.items),
                "superseded_price_list_version_id": (
                    str(superseded.id) if superseded is not None else None
                ),
            },
        )
        await OutboxService().enqueue(session, envelope)
        return PricingCommandResult(activated, envelope.message_id, audit_id)


__all__ = ["PRICE_LIST_VERSION_ACTIVATED", "PricingEffects"]
