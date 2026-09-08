"""Audit and Outbox effects staged on the command's transaction."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.product.application.commands import (
    CommandMetadata,
    ProductCommandResult,
    product_snapshot,
)
from erp.modules.product.domain import Product
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


class ProductEffects:
    async def record(
        self,
        session: AsyncSession,
        product: Product,
        *,
        actor_id: UUID,
        metadata: CommandMetadata,
        event_type: str,
        payload: dict[str, object],
        before: Product | None = None,
        audit_details: dict[str, object] | None = None,
    ) -> ProductCommandResult:
        audit_id = await AuditService().record(
            session,
            AuditEvent(
                actor_user_id=actor_id,
                company_id=product.company_id,
                branch_id=None,
                module="product",
                entity_type="product",
                entity_id=product.id,
                operation=event_type,
                request_id=metadata.request_id,
                correlation_id=metadata.correlation_id,
                source_ip=metadata.source_ip,
                before_snapshot=product_snapshot(before) if before is not None else None,
                after_snapshot={**product_snapshot(product), **(audit_details or {})},
            ),
        )
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=event_type,
            event_version=1,
            producer_module="product",
            producer_domain="product",
            aggregate_type="product",
            aggregate_id=product.id,
            aggregate_version=product.version,
            company_id=product.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            request_id=metadata.request_id,
            causation_id=None,
            payload=payload,
        )
        await OutboxService().enqueue(session, envelope)
        return ProductCommandResult(product, envelope.message_id, audit_id)


__all__ = ["ProductEffects"]
