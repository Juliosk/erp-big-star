"""Monotonic upstream cursors and durable matching re-evaluation work items."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.domain import ThreeWayMatchSession
from erp.modules.procurement.infrastructure.matching_model import (
    MatchingReevaluationModel,
    MatchingSessionModel,
    MatchingSourceCursorModel,
)
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

MATCHING_REEVALUATION_REQUESTED = "MatchingReevaluationRequested"


@dataclass(frozen=True, slots=True)
class MatchingSourceReference:
    producer_module: str
    aggregate_type: str
    aggregate_id: UUID
    captured_version: int | None

    @property
    def key(self) -> str:
        return f"{self.producer_module}:{self.aggregate_type}:{self.aggregate_id}"


async def accept_source_cursor(
    session: AsyncSession,
    envelope: MessageEnvelope,
    *,
    invalidates_snapshot: bool,
) -> bool:
    """Atomically accept only a newer version/timestamp for one upstream aggregate."""
    assert envelope.company_id is not None
    assert envelope.aggregate_version is not None
    proposed = insert(MatchingSourceCursorModel).values(
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
        invalidates_snapshot=invalidates_snapshot,
        payload=envelope.payload,
    )
    newer = or_(
        proposed.excluded.aggregate_version > MatchingSourceCursorModel.aggregate_version,
        and_(
            proposed.excluded.aggregate_version == MatchingSourceCursorModel.aggregate_version,
            proposed.excluded.event_occurred_at
            > MatchingSourceCursorModel.event_occurred_at,
        ),
    )
    statement = (
        proposed.on_conflict_do_update(
            index_elements=[
                MatchingSourceCursorModel.company_id,
                MatchingSourceCursorModel.producer_module,
                MatchingSourceCursorModel.aggregate_type,
                MatchingSourceCursorModel.aggregate_id,
            ],
            set_={
                "aggregate_version": proposed.excluded.aggregate_version,
                "event_id": proposed.excluded.event_id,
                "request_id": proposed.excluded.request_id,
                "correlation_id": proposed.excluded.correlation_id,
                "event_type": proposed.excluded.event_type,
                "event_occurred_at": proposed.excluded.event_occurred_at,
                "invalidates_snapshot": proposed.excluded.invalidates_snapshot,
                "payload": proposed.excluded.payload,
                "updated_at": func.now(),
            },
            where=newer,
        )
        .returning(MatchingSourceCursorModel.aggregate_version)
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None


async def flag_impacted_matching_sessions(
    session: AsyncSession,
    envelope: MessageEnvelope,
    *,
    invalidates_snapshot: bool,
    references: tuple[MatchingSourceReference, ...],
) -> tuple[UUID, ...]:
    """Queue every affected session without changing its immutable source snapshots."""
    assert envelope.company_id is not None
    impacted: dict[UUID, MatchingSessionModel] = {}
    for reference in references:
        roots = await _matching_sessions(session, envelope.company_id, reference)
        for root in roots:
            captured = _captured_version(root, reference)
            if captured is None:
                continue
            if (
                reference.captured_version is None
                or reference.captured_version > captured
                or (invalidates_snapshot and reference.captured_version >= captured)
            ):
                impacted[root.id] = root

    source_reference = MatchingSourceReference(
        envelope.producer_module,
        envelope.aggregate_type,
        envelope.aggregate_id,
        envelope.aggregate_version,
    )
    event_ids = []
    for root in impacted.values():
        await _queue_reevaluation(
            session,
            root=root,
            reference=source_reference,
            envelope=envelope,
            invalidates_snapshot=invalidates_snapshot,
        )
        event_ids.append(
            await _record_reevaluation_effect(
                session,
                root=root,
                reference=source_reference,
                envelope=envelope,
                invalidates_snapshot=invalidates_snapshot,
            )
        )
    return tuple(event_ids)


async def flag_matching_from_source_cursors(
    session: AsyncSession,
    aggregate: ThreeWayMatchSession,
) -> tuple[UUID, ...]:
    """Apply upstream facts that arrived before a matching session was created."""
    event_ids = []
    root = await session.scalar(
        select(MatchingSessionModel).where(
            MatchingSessionModel.company_id == aggregate.company_id,
            MatchingSessionModel.id == aggregate.id,
        )
    )
    if root is None:
        raise RuntimeError("Persisted matching session was not found for cursor evaluation.")
    for reference in matching_source_references(aggregate):
        cursor = await session.scalar(
            select(MatchingSourceCursorModel).where(
                MatchingSourceCursorModel.company_id == aggregate.company_id,
                MatchingSourceCursorModel.producer_module == reference.producer_module,
                MatchingSourceCursorModel.aggregate_type == reference.aggregate_type,
                MatchingSourceCursorModel.aggregate_id == reference.aggregate_id,
            )
        )
        if cursor is None or not _cursor_invalidates_reference(cursor, reference):
            continue
        envelope = _cursor_envelope(cursor)
        await _queue_reevaluation(
            session,
            root=root,
            reference=reference,
            envelope=envelope,
            invalidates_snapshot=cursor.invalidates_snapshot,
        )
        event_ids.append(
            await _record_reevaluation_effect(
                session,
                root=root,
                reference=reference,
                envelope=envelope,
                invalidates_snapshot=cursor.invalidates_snapshot,
            )
        )
    return tuple(event_ids)


def matching_source_references(
    aggregate: ThreeWayMatchSession,
) -> tuple[MatchingSourceReference, ...]:
    purchase = aggregate.purchase_order_snapshot.purchase_order
    receiving = aggregate.receiving_fiscal_snapshot
    financial = aggregate.financial_snapshot
    values = [
        MatchingSourceReference("procurement", "purchase_order", purchase.id, purchase.version),
        *(
            MatchingSourceReference("procurement", "goods_receipt", value.id, value.version)
            for value in receiving.goods_receipts
        ),
        *(
            MatchingSourceReference(
                "fiscal", "inbound_fiscal_document", value.id, value.version
            )
            for value in receiving.fiscal_documents
        ),
        MatchingSourceReference(
            "finance",
            "provisional_financial_entry",
            financial.provisional_entry.id,
            financial.provisional_entry.version,
        ),
    ]
    if financial.payable is not None:
        values.append(
            MatchingSourceReference(
                "finance", "payable", financial.payable.id, financial.payable.version
            )
        )
    return tuple(values)


async def _matching_sessions(
    session: AsyncSession,
    company_id: UUID,
    reference: MatchingSourceReference,
) -> tuple[MatchingSessionModel, ...]:
    statement = select(MatchingSessionModel).where(MatchingSessionModel.company_id == company_id)
    identity = str(reference.aggregate_id)
    if reference.aggregate_type == "purchase_order":
        statement = statement.where(MatchingSessionModel.purchase_order_id == reference.aggregate_id)
    elif reference.aggregate_type == "goods_receipt":
        statement = statement.where(
            MatchingSessionModel.goods_receipts_snapshot.contains([{"id": identity}])
        )
    elif reference.aggregate_type == "inbound_fiscal_document":
        statement = statement.where(
            MatchingSessionModel.fiscal_documents_snapshot.contains([{"id": identity}])
        )
    elif reference.aggregate_type == "provisional_financial_entry":
        statement = statement.where(
            MatchingSessionModel.provisional_entry_id == reference.aggregate_id
        )
    elif reference.aggregate_type == "payable":
        statement = statement.where(MatchingSessionModel.payable_id == reference.aggregate_id)
    else:
        return ()
    return tuple(await session.scalars(statement.with_for_update()))


def _captured_version(
    root: MatchingSessionModel,
    reference: MatchingSourceReference,
) -> int | None:
    if reference.aggregate_type == "purchase_order":
        return root.purchase_order_version
    if reference.aggregate_type == "goods_receipt":
        return _json_reference_version(root.goods_receipts_snapshot, reference.aggregate_id)
    if reference.aggregate_type == "inbound_fiscal_document":
        return _json_reference_version(root.fiscal_documents_snapshot, reference.aggregate_id)
    if reference.aggregate_type == "provisional_financial_entry":
        return root.provisional_entry_version
    if reference.aggregate_type == "payable":
        return root.payable_version
    return None


def _json_reference_version(values: list[dict[str, Any]], identity: UUID) -> int | None:
    for value in values:
        if str(value.get("id")) == str(identity):
            try:
                return int(value["version"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


async def _queue_reevaluation(
    session: AsyncSession,
    *,
    root: MatchingSessionModel,
    reference: MatchingSourceReference,
    envelope: MessageEnvelope,
    invalidates_snapshot: bool,
) -> None:
    watermark = {
        reference.key: {
            "aggregate_version": envelope.aggregate_version,
            "event_id": str(envelope.message_id),
            "event_type": envelope.message_type,
            "occurred_at": envelope.occurred_at.isoformat(),
            "invalidates_snapshot": invalidates_snapshot,
        }
    }
    reason = {
        "source": reference.key,
        "event_type": envelope.message_type,
        "event_id": str(envelope.message_id),
        "aggregate_version": envelope.aggregate_version,
    }
    proposed = insert(MatchingReevaluationModel).values(
        id=uuid4(),
        company_id=root.company_id,
        matching_session_id=root.id,
        status="PENDING",
        required_since=envelope.occurred_at,
        last_event_at=envelope.occurred_at,
        source_watermarks=watermark,
        reasons=[reason],
        revision=1,
    )
    await session.execute(
        proposed.on_conflict_do_update(
            index_elements=[
                MatchingReevaluationModel.company_id,
                MatchingReevaluationModel.matching_session_id,
            ],
            set_={
                "status": "PENDING",
                "last_event_at": func.greatest(
                    MatchingReevaluationModel.last_event_at,
                    proposed.excluded.last_event_at,
                ),
                "source_watermarks": MatchingReevaluationModel.source_watermarks.op("||")(
                    proposed.excluded.source_watermarks
                ),
                "reasons": MatchingReevaluationModel.reasons.op("||")(
                    proposed.excluded.reasons
                ),
                "revision": MatchingReevaluationModel.revision + 1,
            },
        )
    )


async def _record_reevaluation_effect(
    session: AsyncSession,
    *,
    root: MatchingSessionModel,
    reference: MatchingSourceReference,
    envelope: MessageEnvelope,
    invalidates_snapshot: bool,
) -> UUID:
    actor_id = _actor_id(envelope.payload)
    snapshot: dict[str, object] = {
        "matching_session_id": str(root.id),
        "matching_status": root.status,
        "source_module": reference.producer_module,
        "source_type": reference.aggregate_type,
        "source_id": str(reference.aggregate_id),
        "source_version": envelope.aggregate_version,
        "source_event": envelope.message_type,
        "invalidates_snapshot": invalidates_snapshot,
        "reevaluation_status": "PENDING",
    }
    await AuditService().record(
        session,
        AuditEvent(
            actor_user_id=actor_id,
            company_id=root.company_id,
            branch_id=None,
            module="procurement",
            entity_type="three_way_match_session",
            entity_id=root.id,
            operation=MATCHING_REEVALUATION_REQUESTED,
            request_id=envelope.request_id,
            correlation_id=envelope.correlation_id,
            after_snapshot=snapshot,
            reason_code=envelope.message_type,
        ),
    )
    outgoing = MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=MATCHING_REEVALUATION_REQUESTED,
        event_version=1,
        producer_module="procurement",
        producer_domain="procurement",
        aggregate_type="three_way_match_session",
        aggregate_id=root.id,
        aggregate_version=root.version,
        company_id=root.company_id,
        branch_id=None,
        correlation_id=envelope.correlation_id,
        causation_id=envelope.message_id,
        request_id=envelope.request_id,
        payload=snapshot,
    )
    await OutboxService().enqueue(session, outgoing)
    return outgoing.message_id


def _cursor_invalidates_reference(
    cursor: MatchingSourceCursorModel,
    reference: MatchingSourceReference,
) -> bool:
    assert reference.captured_version is not None
    return cursor.aggregate_version > reference.captured_version or (
        cursor.invalidates_snapshot and cursor.aggregate_version >= reference.captured_version
    )


def _cursor_envelope(cursor: MatchingSourceCursorModel) -> MessageEnvelope:
    return MessageEnvelope(
        message_id=cursor.event_id,
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=cursor.event_type,
        event_version=1,
        producer_module=cursor.producer_module,
        producer_domain=cursor.producer_module,
        aggregate_type=cursor.aggregate_type,
        aggregate_id=cursor.aggregate_id,
        aggregate_version=cursor.aggregate_version,
        company_id=cursor.company_id,
        branch_id=None,
        occurred_at=cursor.event_occurred_at,
        correlation_id=cursor.correlation_id,
        causation_id=None,
        request_id=cursor.request_id,
        payload=cursor.payload,
    )


def _actor_id(payload: dict[str, Any]) -> UUID | None:
    for field in ("actor_id", "requested_by", "decided_by", "created_by"):
        try:
            value = payload.get(field)
            if value is not None:
                return UUID(str(value))
        except (TypeError, ValueError):
            continue
    return None


__all__ = [
    "MATCHING_REEVALUATION_REQUESTED",
    "MatchingSourceReference",
    "accept_source_cursor",
    "flag_impacted_matching_sessions",
    "flag_matching_from_source_cursors",
    "matching_source_references",
]
