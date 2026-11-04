"""Monotonic event state and durable Cash Flow recomposition work."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import (
    CashFlowAlertMetadata,
    CashFlowAlertService,
    CashFlowCompositionService,
    ComposeCashFlowProjection,
    ReceivableCashFlowProvider,
    UnavailableReceivableProvider,
)
from erp.modules.finance.domain import (
    BusinessCalendar,
    CashFlowAlertEngine,
    CashFlowAlertPolicy,
    CashFlowAlertSource,
    CashFlowCertainty,
    CashFlowEngine,
    CashFlowOrigin,
)
from erp.modules.finance.infrastructure.cash_flow_alerts import (
    PostgresCashFlowAlertRecorder,
)
from erp.modules.finance.infrastructure.cash_flow_event_model import (
    CashFlowRecompositionRequestModel,
    CashFlowSourceCursorModel,
)
from erp.modules.finance.infrastructure.cash_flow_model import CashFlowProjectionSnapshotModel
from erp.modules.finance.infrastructure.cash_flow_repository import CashFlowProjectionRepository
from erp.modules.finance.infrastructure.cash_flow_sources import (
    PostgresBankPositionProvider,
    PostgresPayableCommitmentProvider,
)
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

CASH_FLOW_PROJECTION_RECOMPOSED = "CashFlowProjectionRecomposed"

ReceivableProviderFactory = Callable[[AsyncSession], ReceivableCashFlowProvider]
Clock = Callable[[], datetime]


async def accept_cash_flow_source_cursor(
    session: AsyncSession,
    envelope: MessageEnvelope,
) -> bool:
    """Accept only a strictly newer version/timestamp for one upstream aggregate."""
    assert envelope.company_id is not None
    assert envelope.aggregate_version is not None
    proposed = insert(CashFlowSourceCursorModel).values(
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
        proposed.excluded.aggregate_version > CashFlowSourceCursorModel.aggregate_version,
        and_(
            proposed.excluded.aggregate_version == CashFlowSourceCursorModel.aggregate_version,
            proposed.excluded.event_occurred_at > CashFlowSourceCursorModel.event_occurred_at,
        ),
    )
    statement = proposed.on_conflict_do_update(
        index_elements=[
            CashFlowSourceCursorModel.company_id,
            CashFlowSourceCursorModel.producer_module,
            CashFlowSourceCursorModel.aggregate_type,
            CashFlowSourceCursorModel.aggregate_id,
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
    ).returning(CashFlowSourceCursorModel.aggregate_version)
    return (await session.execute(statement)).scalar_one_or_none() is not None


async def enqueue_cash_flow_recompositions(
    session: AsyncSession,
    envelope: MessageEnvelope,
    *,
    requested_at: datetime,
) -> tuple[UUID, ...]:
    """Coalesce one accepted fact into durable work for every tenant projection."""
    assert envelope.company_id is not None
    assert envelope.aggregate_version is not None
    projection_ids = tuple(
        await session.scalars(
            select(CashFlowProjectionSnapshotModel.id)
            .where(CashFlowProjectionSnapshotModel.company_id == envelope.company_id)
            .distinct()
            .order_by(CashFlowProjectionSnapshotModel.id)
        )
    )
    for projection_id in projection_ids:
        proposed = insert(CashFlowRecompositionRequestModel).values(
            company_id=envelope.company_id,
            projection_id=projection_id,
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
                    CashFlowRecompositionRequestModel.company_id,
                    CashFlowRecompositionRequestModel.projection_id,
                ],
                set_={
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
                    "revision": CashFlowRecompositionRequestModel.revision + 1,
                },
            )
        )
    return projection_ids


class CashFlowRecompositionWorker:
    """Claim queued projections without waiting and persist their next versions."""

    def __init__(
        self,
        *,
        receivables: ReceivableProviderFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._receivables = receivables or (lambda _session: UnavailableReceivableProvider())
        self._clock = clock or (lambda: datetime.now(UTC))

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
                select(CashFlowRecompositionRequestModel)
                .where(CashFlowRecompositionRequestModel.company_id == company_id)
                .order_by(
                    CashFlowRecompositionRequestModel.requested_at,
                    CashFlowRecompositionRequestModel.projection_id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        completed: list[UUID] = []
        for request in requests:
            repository = CashFlowProjectionRepository(session, company_id=company_id)
            current = await repository.claim_latest(request.projection_id)
            if current is None:
                continue
            calculated_at = max(
                self._clock(),
                request.source_occurred_at,
                current.calculated_at + timedelta(microseconds=1),
            )
            predicted = tuple(
                item
                for item in current.source_items
                if item.certainty is CashFlowCertainty.SCENARIO
                and item.origin is CashFlowOrigin.MANUAL_SCENARIO
            )
            result = await CashFlowCompositionService(
                engine=CashFlowEngine(BusinessCalendar()),
                bank_positions=PostgresBankPositionProvider(session),
                payables=PostgresPayableCommitmentProvider(session),
                receivables=self._receivables(session),
                projections=repository,
            ).compose(
                ComposeCashFlowProjection(
                    projection_id=current.id,
                    company_id=current.company_id,
                    as_of=current.as_of,
                    calculated_at=calculated_at,
                    horizon=current.horizon,
                    granularity=current.granularity,
                    minimum_reserve=current.minimum_reserve,
                    scenario=current.scenario,
                    predicted_items=predicted,
                    currency=current.opening_balance.currency,
                ),
                actor_id=request.source_event_id,
            )
            await CashFlowAlertService(
                CashFlowAlertEngine(CashFlowAlertPolicy()),
                PostgresCashFlowAlertRecorder(session),
            ).evaluate_and_record(
                result.projection,
                source=CashFlowAlertSource.PROJECTION,
                metadata=CashFlowAlertMetadata(
                    actor_id=request.source_event_id,
                    request_id=request.request_id,
                    correlation_id=request.correlation_id,
                    detected_at=calculated_at,
                ),
            )
            outgoing = MessageEnvelope.new(
                message_kind=MessageKind.DOMAIN_EVENT,
                message_type=CASH_FLOW_PROJECTION_RECOMPOSED,
                event_version=1,
                producer_module="finance",
                producer_domain="cash_flow",
                aggregate_type="cash_flow_projection",
                aggregate_id=result.projection.id,
                aggregate_version=result.projection.version,
                company_id=company_id,
                branch_id=None,
                correlation_id=request.correlation_id,
                causation_id=request.source_event_id,
                request_id=request.request_id,
                payload={
                    "company_id": str(company_id),
                    "projection_id": str(result.projection.id),
                    "projection_version": result.projection.version,
                    "source_event": request.source_event_type,
                    "source_aggregate_type": request.source_aggregate_type,
                    "source_aggregate_id": str(request.source_aggregate_id),
                    "source_aggregate_version": request.source_aggregate_version,
                    "liquidity_state": result.projection.liquidity_state.value,
                    "source_gap_count": len(result.source_gaps),
                },
            )
            await OutboxService().enqueue(session, outgoing)
            await session.execute(
                delete(CashFlowRecompositionRequestModel).where(
                    CashFlowRecompositionRequestModel.company_id == company_id,
                    CashFlowRecompositionRequestModel.projection_id == request.projection_id,
                    CashFlowRecompositionRequestModel.revision == request.revision,
                )
            )
            completed.append(request.projection_id)
        return tuple(completed)


__all__ = [
    "CASH_FLOW_PROJECTION_RECOMPOSED",
    "CashFlowRecompositionWorker",
    "accept_cash_flow_source_cursor",
    "enqueue_cash_flow_recompositions",
]
