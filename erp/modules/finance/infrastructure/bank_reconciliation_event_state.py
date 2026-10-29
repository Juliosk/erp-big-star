"""Monotonic projections and reactive matching effects for bank reconciliation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import (
    BankCandidateSource,
    BankConciliationService,
    CompositeBankCandidateProvider,
)
from erp.modules.finance.domain import BankMovementDirection
from erp.modules.finance.infrastructure.bank_reconciliation_candidates import (
    PayableBankCandidateProvider,
)
from erp.modules.finance.infrastructure.bank_reconciliation_event_candidates import (
    EventBankCandidateProvider,
)
from erp.modules.finance.infrastructure.bank_reconciliation_event_model import (
    BankReconciliationCandidateModel,
    BankReconciliationSourceCursorModel,
)
from erp.modules.finance.infrastructure.bank_reconciliation_events import (
    publish_reconciled_movements,
    publish_reconciliation_review,
)
from erp.modules.finance.infrastructure.bank_statement_model import (
    BankMovementModel,
    BankStatementModel,
    ConciliationRecordModel,
)
from erp.modules.finance.infrastructure.bank_statement_repository import (
    BankStatementRepository,
)
from erp.platform.messaging import MessageEnvelope


@dataclass(frozen=True, slots=True)
class BankCandidateProjection:
    reference_id: UUID
    source: BankCandidateSource
    expected_on: date
    amount: Decimal
    direction: BankMovementDirection
    document_number: str | None


async def accept_bank_reconciliation_cursor(
    session: AsyncSession,
    envelope: MessageEnvelope,
) -> bool:
    """Accept only a strictly newer version/timestamp for one tenant source."""
    assert envelope.company_id is not None
    assert envelope.aggregate_version is not None
    proposed = insert(BankReconciliationSourceCursorModel).values(
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
        payload=envelope.payload,
    )
    newer = or_(
        proposed.excluded.aggregate_version
        > BankReconciliationSourceCursorModel.aggregate_version,
        and_(
            proposed.excluded.aggregate_version
            == BankReconciliationSourceCursorModel.aggregate_version,
            proposed.excluded.event_occurred_at
            > BankReconciliationSourceCursorModel.event_occurred_at,
        ),
    )
    statement = proposed.on_conflict_do_update(
        index_elements=[
            BankReconciliationSourceCursorModel.company_id,
            BankReconciliationSourceCursorModel.producer_module,
            BankReconciliationSourceCursorModel.aggregate_type,
            BankReconciliationSourceCursorModel.aggregate_id,
        ],
        set_={
            "aggregate_version": proposed.excluded.aggregate_version,
            "event_id": proposed.excluded.event_id,
            "request_id": proposed.excluded.request_id,
            "correlation_id": proposed.excluded.correlation_id,
            "event_type": proposed.excluded.event_type,
            "event_occurred_at": proposed.excluded.event_occurred_at,
            "payload": proposed.excluded.payload,
            "updated_at": func.now(),
        },
        where=newer,
    ).returning(BankReconciliationSourceCursorModel.aggregate_version)
    return (await session.execute(statement)).scalar_one_or_none() is not None


async def upsert_event_candidate(
    session: AsyncSession,
    envelope: MessageEnvelope,
    projection: BankCandidateProjection,
) -> None:
    assert envelope.company_id is not None
    assert envelope.aggregate_version is not None
    statement = insert(BankReconciliationCandidateModel).values(
        id=projection.reference_id,
        company_id=envelope.company_id,
        source=projection.source.value,
        expected_on=projection.expected_on,
        amount=projection.amount,
        direction=projection.direction.value,
        document_number=projection.document_number,
        active=True,
        source_version=envelope.aggregate_version,
        source_event_id=envelope.message_id,
        source_occurred_at=envelope.occurred_at,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[BankReconciliationCandidateModel.id],
            set_={
                "source": statement.excluded.source,
                "expected_on": statement.excluded.expected_on,
                "amount": statement.excluded.amount,
                "direction": statement.excluded.direction,
                "document_number": statement.excluded.document_number,
                "active": True,
                "source_version": statement.excluded.source_version,
                "source_event_id": statement.excluded.source_event_id,
                "source_occurred_at": statement.excluded.source_occurred_at,
                "updated_at": func.now(),
            },
        )
    )


async def deactivate_event_candidate(
    session: AsyncSession,
    envelope: MessageEnvelope,
    reference_id: UUID,
) -> None:
    assert envelope.company_id is not None
    assert envelope.aggregate_version is not None
    await session.execute(
        update(BankReconciliationCandidateModel)
        .where(
            BankReconciliationCandidateModel.company_id == envelope.company_id,
            BankReconciliationCandidateModel.id == reference_id,
            BankReconciliationCandidateModel.source_version <= envelope.aggregate_version,
        )
        .values(
            active=False,
            source_version=envelope.aggregate_version,
            source_event_id=envelope.message_id,
            source_occurred_at=envelope.occurred_at,
            updated_at=func.now(),
        )
    )


async def reevaluate_pending_statements(
    session: AsyncSession,
    envelope: MessageEnvelope,
) -> tuple[UUID, ...]:
    """Lock pending statements and atomically apply newly unambiguous matches."""
    assert envelope.company_id is not None
    pending = exists(
        select(BankMovementModel.id).where(
            BankMovementModel.company_id == BankStatementModel.company_id,
            BankMovementModel.bank_statement_id == BankStatementModel.id,
            BankMovementModel.status == "PENDING",
        )
    )
    roots = tuple(
        await session.scalars(
            select(BankStatementModel)
            .where(
                BankStatementModel.company_id == envelope.company_id,
                pending,
            )
            .order_by(BankStatementModel.period_start, BankStatementModel.id)
            .with_for_update(skip_locked=True)
        )
    )
    repository = BankStatementRepository(session, company_id=envelope.company_id)
    provider = CompositeBankCandidateProvider(
        PayableBankCandidateProvider(session, company_id=envelope.company_id),
        EventBankCandidateProvider(session, company_id=envelope.company_id),
    )
    changed = []
    for root in roots:
        before = await repository.get(root.id)
        if before is None:
            continue
        result = await BankConciliationService(repository, provider).reconcile(
            root.id,
            actor_id=envelope.message_id,
            occurred_at=envelope.occurred_at,
        )
        if result.statement.version == before.version:
            continue
        await publish_reconciled_movements(
            session,
            before=before,
            result=result,
            request_id=envelope.request_id,
            correlation_id=envelope.correlation_id,
            causation_id=envelope.message_id,
        )
        changed.append(root.id)
    return tuple(changed)


async def flag_reversed_reconciliations(
    session: AsyncSession,
    envelope: MessageEnvelope,
    reference_id: UUID,
) -> tuple[UUID, ...]:
    """Keep immutable reconciliation evidence and raise review facts after reversal."""
    assert envelope.company_id is not None
    rows = await session.execute(
        select(ConciliationRecordModel, BankStatementModel)
        .join(
            BankStatementModel,
            (BankStatementModel.company_id == ConciliationRecordModel.company_id)
            & (BankStatementModel.id == ConciliationRecordModel.bank_statement_id),
        )
        .where(
            ConciliationRecordModel.company_id == envelope.company_id,
            ConciliationRecordModel.matched_reference_id == reference_id,
        )
        .with_for_update(of=BankStatementModel)
    )
    event_ids = []
    for record, root in rows.all():
        statement = await BankStatementRepository(
            session, company_id=envelope.company_id
        ).get(root.id)
        if statement is None:
            continue
        event_ids.append(
            await publish_reconciliation_review(
                session,
                statement=statement,
                movement_id=record.bank_movement_id,
                reference_id=reference_id,
                request_id=envelope.request_id,
                correlation_id=envelope.correlation_id,
                causation_id=envelope.message_id,
                reason="The matched financial settlement was reversed upstream.",
            )
        )
    return tuple(event_ids)


__all__ = [
    "BankCandidateProjection",
    "accept_bank_reconciliation_cursor",
    "deactivate_event_candidate",
    "flag_reversed_reconciliations",
    "reevaluate_pending_statements",
    "upsert_event_candidate",
]
