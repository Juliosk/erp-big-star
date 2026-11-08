"""Inbox-backed consumer for resilient cross-module Production synchronization."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.production.infrastructure.production_event_state import (
    ProductionSynchronizationWorker,
    accept_production_source_cursor,
    enqueue_production_synchronizations,
)
from erp.platform.database import Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope, MessageKind

PRODUCTION_EVENT_CONSUMER = "production.cross-module-events.v1"

_SUPPORTED_EVENTS = {
    "InventoryAdjusted": ("inventory", "inventory", "inventory_adjustment"),
    "ProductUpdated": ("product", "product", "product"),
    "BillOfMaterialsUpdated": ("production", "engineering", "bill_of_materials"),
    "RoutingUpdated": ("production", "engineering", "production_routing"),
}


class ProductionEventConsumer:
    """Accept upstream tenant facts once and synchronize affected OPs."""

    def __init__(
        self,
        database: Database,
        *,
        inbox: InboxService | None = None,
        worker: ProductionSynchronizationWorker | None = None,
    ) -> None:
        self._database = database
        self._inbox = inbox or InboxService()
        self._worker = worker or ProductionSynchronizationWorker()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        _validate_envelope(envelope)

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            if not await accept_production_source_cursor(session, message):
                return
            await enqueue_production_synchronizations(
                session,
                message,
                requested_at=datetime.now(UTC),
            )

        async with self._database.session() as session, session.begin():
            result = await self._inbox.process(
                session,
                consumer_name=PRODUCTION_EVENT_CONSUMER,
                envelope=envelope,
                effect=effect,
            )
        assert envelope.company_id is not None
        async with self._database.session() as session, session.begin():
            await self._worker.run_pending(session, company_id=envelope.company_id)
        return result


def _validate_envelope(envelope: MessageEnvelope) -> None:
    policy = _SUPPORTED_EVENTS.get(envelope.message_type)
    if (
        policy is None
        or envelope.message_kind is not MessageKind.DOMAIN_EVENT
        or envelope.event_version != 1
        or envelope.company_id is None
        or envelope.aggregate_version is None
        or (envelope.producer_module, envelope.producer_domain, envelope.aggregate_type)
        != policy
        or envelope.occurred_at.tzinfo is None
        or envelope.occurred_at.utcoffset() is None
    ):
        raise ValueError("Unsupported Production source event envelope.")
    payload_company = envelope.payload.get("company_id")
    if payload_company is not None and str(payload_company) != str(envelope.company_id):
        raise ValueError("Production source event crosses the company boundary.")


__all__ = ["PRODUCTION_EVENT_CONSUMER", "ProductionEventConsumer"]
