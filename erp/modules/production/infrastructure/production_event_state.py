"""Monotonic upstream state and durable Production synchronization work."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.production.infrastructure.production_event_model import (
    ProductionSourceCursorModel,
    ProductionSynchronizationRequestModel,
)
from erp.modules.production.infrastructure.production_order_model import (
    ProductionOrderItemPlanModel,
    ProductionOrderModel,
)
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

PRODUCTION_SYNCHRONIZATION_REQUESTED = "ProductionSynchronizationRequested"
_ACTIVE_STATUSES = ("DRAFT", "RELEASED", "IN_PROGRESS")


async def accept_production_source_cursor(
    session: AsyncSession,
    envelope: MessageEnvelope,
) -> bool:
    """Accept only a newer version or a later fact at the same version."""
    assert envelope.company_id is not None
    assert envelope.aggregate_version is not None
    proposed = insert(ProductionSourceCursorModel).values(
        company_id=envelope.company_id,
        producer_module=envelope.producer_module,
        aggregate_type=envelope.aggregate_type,
        aggregate_id=envelope.aggregate_id,
        aggregate_version=envelope.aggregate_version,
        event_id=envelope.message_id,
        request_id=envelope.request_id,
        correlation_id=envelope.correlation_id,
        event_type=envelope.message_type,
        event_occurred_at=envelope.occurred_at,
    )
    newer = or_(
        proposed.excluded.aggregate_version > ProductionSourceCursorModel.aggregate_version,
        and_(
            proposed.excluded.aggregate_version
            == ProductionSourceCursorModel.aggregate_version,
            proposed.excluded.event_occurred_at
            > ProductionSourceCursorModel.event_occurred_at,
        ),
    )
    statement = proposed.on_conflict_do_update(
        index_elements=[
            ProductionSourceCursorModel.company_id,
            ProductionSourceCursorModel.producer_module,
            ProductionSourceCursorModel.aggregate_type,
            ProductionSourceCursorModel.aggregate_id,
        ],
        set_={
            "aggregate_version": proposed.excluded.aggregate_version,
            "event_id": proposed.excluded.event_id,
            "request_id": proposed.excluded.request_id,
            "correlation_id": proposed.excluded.correlation_id,
            "event_type": proposed.excluded.event_type,
            "event_occurred_at": proposed.excluded.event_occurred_at,
            "updated_at": func.now(),
        },
        where=newer,
    ).returning(ProductionSourceCursorModel.aggregate_version)
    return (await session.execute(statement)).scalar_one_or_none() is not None


async def enqueue_production_synchronizations(
    session: AsyncSession,
    envelope: MessageEnvelope,
    *,
    requested_at: datetime,
) -> tuple[UUID, ...]:
    """Coalesce an accepted stock/engineering fact for every affected active OP."""
    assert envelope.company_id is not None
    assert envelope.aggregate_version is not None
    product_ids = _affected_product_ids(envelope)
    if not product_ids:
        return ()
    component_match = exists(
        select(ProductionOrderItemPlanModel.id).where(
            ProductionOrderItemPlanModel.company_id == envelope.company_id,
            ProductionOrderItemPlanModel.production_order_id == ProductionOrderModel.id,
            ProductionOrderItemPlanModel.component_product_id.in_(product_ids),
        )
    )
    order_ids = tuple(
        await session.scalars(
            select(ProductionOrderModel.id)
            .where(
                ProductionOrderModel.company_id == envelope.company_id,
                ProductionOrderModel.status.in_(_ACTIVE_STATUSES),
                or_(ProductionOrderModel.product_id.in_(product_ids), component_match),
            )
            .order_by(ProductionOrderModel.id)
        )
    )
    reason = _reason(envelope)
    serialized_products = sorted(str(value) for value in product_ids)
    for order_id in order_ids:
        proposed = insert(ProductionSynchronizationRequestModel).values(
            company_id=envelope.company_id,
            production_order_id=order_id,
            reason=reason,
            affected_product_ids=serialized_products,
            source_event_id=envelope.message_id,
            source_event_type=envelope.message_type,
            source_producer_module=envelope.producer_module,
            source_aggregate_type=envelope.aggregate_type,
            source_aggregate_id=envelope.aggregate_id,
            source_aggregate_version=envelope.aggregate_version,
            source_occurred_at=envelope.occurred_at,
            request_id=envelope.request_id,
            correlation_id=envelope.correlation_id,
            requested_at=requested_at,
            revision=1,
        )
        await session.execute(
            proposed.on_conflict_do_update(
                index_elements=[
                    ProductionSynchronizationRequestModel.company_id,
                    ProductionSynchronizationRequestModel.production_order_id,
                ],
                set_={
                    "reason": proposed.excluded.reason,
                    "affected_product_ids": proposed.excluded.affected_product_ids,
                    "source_event_id": proposed.excluded.source_event_id,
                    "source_event_type": proposed.excluded.source_event_type,
                    "source_producer_module": proposed.excluded.source_producer_module,
                    "source_aggregate_type": proposed.excluded.source_aggregate_type,
                    "source_aggregate_id": proposed.excluded.source_aggregate_id,
                    "source_aggregate_version": proposed.excluded.source_aggregate_version,
                    "source_occurred_at": proposed.excluded.source_occurred_at,
                    "request_id": proposed.excluded.request_id,
                    "correlation_id": proposed.excluded.correlation_id,
                    "requested_at": proposed.excluded.requested_at,
                    "revision": ProductionSynchronizationRequestModel.revision + 1,
                },
            )
        )
    return order_ids


class ProductionSynchronizationWorker:
    """Claim reevaluation requests without waiting on competing workers."""

    async def run_pending(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        limit: int = 25,
    ) -> tuple[UUID, ...]:
        if type(limit) is not int or limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500.")
        requests = tuple(
            await session.scalars(
                select(ProductionSynchronizationRequestModel)
                .where(ProductionSynchronizationRequestModel.company_id == company_id)
                .order_by(
                    ProductionSynchronizationRequestModel.requested_at,
                    ProductionSynchronizationRequestModel.production_order_id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        completed: list[UUID] = []
        for request in requests:
            order = await session.scalar(
                select(ProductionOrderModel).where(
                    ProductionOrderModel.company_id == company_id,
                    ProductionOrderModel.id == request.production_order_id,
                )
            )
            if order is not None:
                envelope = MessageEnvelope.new(
                    message_kind=MessageKind.DOMAIN_EVENT,
                    message_type=PRODUCTION_SYNCHRONIZATION_REQUESTED,
                    event_version=1,
                    producer_module="production",
                    producer_domain="production",
                    aggregate_type="production_order",
                    aggregate_id=order.id,
                    aggregate_version=order.version,
                    company_id=company_id,
                    branch_id=None,
                    correlation_id=request.correlation_id,
                    causation_id=request.source_event_id,
                    request_id=request.request_id,
                    payload={
                        "company_id": str(company_id),
                        "production_order_id": str(order.id),
                        "production_order_status": order.status,
                        "reason": request.reason,
                        "affected_product_ids": request.affected_product_ids,
                        "source_event": request.source_event_type,
                        "source_aggregate_type": request.source_aggregate_type,
                        "source_aggregate_id": str(request.source_aggregate_id),
                        "source_aggregate_version": request.source_aggregate_version,
                    },
                )
                await OutboxService().enqueue(session, envelope)
            await session.execute(
                delete(ProductionSynchronizationRequestModel).where(
                    ProductionSynchronizationRequestModel.company_id == company_id,
                    ProductionSynchronizationRequestModel.production_order_id
                    == request.production_order_id,
                    ProductionSynchronizationRequestModel.revision == request.revision,
                )
            )
            completed.append(request.production_order_id)
        return tuple(completed)


def _affected_product_ids(envelope: MessageEnvelope) -> tuple[UUID, ...]:
    raw: list[object] = []
    if envelope.message_type == "InventoryAdjusted":
        postings = envelope.payload.get("postings", [])
        if isinstance(postings, list):
            raw.extend(
                value.get("product_id")
                for value in postings
                if isinstance(value, dict) and value.get("product_id") is not None
            )
    else:
        raw.append(envelope.payload.get("product_id", envelope.aggregate_id))
    parsed: set[UUID] = set()
    for value in raw:
        try:
            parsed.add(UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    return tuple(sorted(parsed, key=str))


def _reason(envelope: MessageEnvelope) -> str:
    if envelope.message_type == "InventoryAdjusted":
        return "STOCK_CHANGED"
    if envelope.message_type == "ProductUpdated":
        return "PRODUCT_CHANGED"
    return "ENGINEERING_CHANGED"


__all__ = [
    "PRODUCTION_SYNCHRONIZATION_REQUESTED",
    "ProductionSynchronizationWorker",
    "accept_production_source_cursor",
    "enqueue_production_synchronizations",
]
