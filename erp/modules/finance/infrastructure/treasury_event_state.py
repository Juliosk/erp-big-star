"""Monotonic source cursors and durable payment-batch reassessment effects."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.domain import PaymentBatch
from erp.modules.finance.infrastructure.treasury_event_model import (
    PaymentBatchReviewModel,
    TreasurySourceCursorModel,
)
from erp.modules.finance.infrastructure.treasury_model import (
    PaymentBatchItemModel,
    PaymentBatchModel,
)
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

PAYMENT_BATCH_BLOCKED = "PaymentBatchBlocked"
PAYMENT_BATCH_REEVALUATION_REQUESTED = "PaymentBatchReevaluationRequested"
PAYMENT_BATCH_REEVALUATION_CLEARED = "PaymentBatchReevaluationCleared"

_MUTABLE_BATCH_STATUSES = ("DRAFT", "PENDING_APPROVAL")


class TreasuryReviewStatus(StrEnum):
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CLEARED = "CLEARED"


@dataclass(frozen=True, slots=True)
class TreasuryAssessment:
    status: TreasuryReviewStatus
    blocked: bool
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.status, TreasuryReviewStatus):
            raise TypeError("status must be a TreasuryReviewStatus.")
        if type(self.blocked) is not bool:
            raise TypeError("blocked must be boolean.")
        if not self.reason.strip() or len(self.reason.strip()) > 500:
            raise ValueError("reason must contain between 1 and 500 characters.")
        if self.status is TreasuryReviewStatus.CLEARED and self.blocked:
            raise ValueError("A cleared Treasury assessment cannot remain blocked.")
        if self.status is not TreasuryReviewStatus.CLEARED and not self.blocked:
            raise ValueError("A pending Treasury assessment must block remittance.")


async def accept_treasury_source_cursor(
    session: AsyncSession,
    envelope: MessageEnvelope,
    assessment: TreasuryAssessment,
) -> bool:
    """Accept only a strictly newer version/timestamp for one upstream aggregate."""
    assert envelope.company_id is not None
    assert envelope.aggregate_version is not None
    payload = {
        **envelope.payload,
        "_treasury_assessment": {
            "status": assessment.status.value,
            "blocked": assessment.blocked,
            "reason": assessment.reason,
        },
    }
    proposed = insert(TreasurySourceCursorModel).values(
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
        payload=payload,
    )
    newer = or_(
        proposed.excluded.aggregate_version > TreasurySourceCursorModel.aggregate_version,
        and_(
            proposed.excluded.aggregate_version == TreasurySourceCursorModel.aggregate_version,
            proposed.excluded.event_occurred_at > TreasurySourceCursorModel.event_occurred_at,
        ),
    )
    statement = proposed.on_conflict_do_update(
        index_elements=[
            TreasurySourceCursorModel.company_id,
            TreasurySourceCursorModel.producer_module,
            TreasurySourceCursorModel.aggregate_type,
            TreasurySourceCursorModel.aggregate_id,
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
    ).returning(TreasurySourceCursorModel.aggregate_version)
    return (await session.execute(statement)).scalar_one_or_none() is not None


async def reassess_impacted_payment_batches(
    session: AsyncSession,
    envelope: MessageEnvelope,
    assessment: TreasuryAssessment,
) -> tuple[UUID, ...]:
    """Merge one accepted external fact into every mutable impacted payment batch."""
    batches = await _impacted_batches(session, envelope)
    event_ids = []
    for batch in batches:
        event_ids.append(
            await _apply_assessment(
                session,
                batch=batch,
                envelope=envelope,
                assessment=assessment,
            )
        )
    return tuple(event_ids)


async def apply_treasury_source_cursors(
    session: AsyncSession,
    batch: PaymentBatch,
) -> tuple[UUID, ...]:
    """Apply relevant facts that were delivered before a batch was created."""
    model = await session.scalar(
        select(PaymentBatchModel)
        .where(
            PaymentBatchModel.company_id == batch.company_id,
            PaymentBatchModel.id == batch.id,
        )
        .with_for_update()
    )
    if model is None:
        raise RuntimeError("Persisted payment batch was not found for cursor evaluation.")
    references = {("finance", "payable", item.payable_id) for item in batch.items} | {
        ("procurement", "three_way_match_session", item.matching_session_id) for item in batch.items
    }
    event_ids = []
    for producer, aggregate_type, aggregate_id in references:
        cursor = await session.scalar(
            select(TreasurySourceCursorModel).where(
                TreasurySourceCursorModel.company_id == batch.company_id,
                TreasurySourceCursorModel.producer_module == producer,
                TreasurySourceCursorModel.aggregate_type == aggregate_type,
                TreasurySourceCursorModel.aggregate_id == aggregate_id,
            )
        )
        if cursor is None:
            continue
        assessment = _cursor_assessment(cursor)
        event_ids.append(
            await _apply_assessment(
                session,
                batch=model,
                envelope=_cursor_envelope(cursor),
                assessment=assessment,
            )
        )
    return tuple(event_ids)


async def require_payment_batch_unblocked(
    session: AsyncSession,
    *,
    company_id: UUID,
    payment_batch_id: UUID,
) -> None:
    review = await session.scalar(
        select(PaymentBatchReviewModel).where(
            PaymentBatchReviewModel.company_id == company_id,
            PaymentBatchReviewModel.payment_batch_id == payment_batch_id,
        )
    )
    if review is None or not review.blocked:
        return
    raise ApplicationError(
        code="PAYMENT_BATCH_REVIEW_BLOCKED",
        message="Payment batch requires Treasury reassessment before remittance.",
        status_code=409,
        details=[
            ErrorDetail(
                message=(f"Treasury review is {review.status} at revision {review.revision}.")
            )
        ],
    )


async def _impacted_batches(
    session: AsyncSession,
    envelope: MessageEnvelope,
) -> tuple[PaymentBatchModel, ...]:
    assert envelope.company_id is not None
    base = select(PaymentBatchModel).where(
        PaymentBatchModel.company_id == envelope.company_id,
        PaymentBatchModel.status.in_(_MUTABLE_BATCH_STATUSES),
    )
    if envelope.producer_module == "workflow":
        batch_id = _payload_uuid(envelope.payload, "source_id")
        statement = base.where(PaymentBatchModel.id == batch_id)
    else:
        statement = base.join(
            PaymentBatchItemModel,
            (PaymentBatchItemModel.company_id == PaymentBatchModel.company_id)
            & (PaymentBatchItemModel.payment_batch_id == PaymentBatchModel.id),
        )
        if envelope.aggregate_type == "payable":
            statement = statement.where(PaymentBatchItemModel.payable_id == envelope.aggregate_id)
        elif envelope.aggregate_type == "three_way_match_session":
            statement = statement.where(
                PaymentBatchItemModel.matching_session_id == envelope.aggregate_id
            )
        elif envelope.aggregate_type == "fiscal_receiving_reconciliation":
            payable_id = _optional_payload_uuid(envelope.payload, "payable_id")
            matching_id = _optional_payload_uuid(envelope.payload, "matching_session_id")
            conditions = []
            if payable_id is not None:
                conditions.append(PaymentBatchItemModel.payable_id == payable_id)
            if matching_id is not None:
                conditions.append(PaymentBatchItemModel.matching_session_id == matching_id)
            if not conditions:
                return ()
            statement = statement.where(or_(*conditions))
        else:
            return ()
    result = await session.scalars(statement.with_for_update(of=PaymentBatchModel))
    return tuple(result.unique())


async def _apply_assessment(
    session: AsyncSession,
    *,
    batch: PaymentBatchModel,
    envelope: MessageEnvelope,
    assessment: TreasuryAssessment,
) -> UUID:
    review = await session.scalar(
        select(PaymentBatchReviewModel)
        .where(
            PaymentBatchReviewModel.company_id == batch.company_id,
            PaymentBatchReviewModel.payment_batch_id == batch.id,
        )
        .with_for_update()
    )
    source_key = f"{envelope.producer_module}:{envelope.aggregate_type}:{envelope.aggregate_id}"
    source_states: dict[str, Any] = {} if review is None else dict(review.source_states)
    source_states[source_key] = {
        "aggregate_version": envelope.aggregate_version,
        "event_id": str(envelope.message_id),
        "event_type": envelope.message_type,
        "occurred_at": envelope.occurred_at.isoformat(),
        "status": assessment.status.value,
        "blocked": assessment.blocked,
        "reason": assessment.reason,
    }
    status, blocked = _merged_status(source_states)
    reason = {
        "source": source_key,
        "event_id": str(envelope.message_id),
        "event_type": envelope.message_type,
        "aggregate_version": envelope.aggregate_version,
        "assessment": assessment.status.value,
        "reason": assessment.reason,
    }
    previous = None if review is None else _review_snapshot(review)
    if review is None:
        review = PaymentBatchReviewModel(
            id=uuid4(),
            company_id=batch.company_id,
            payment_batch_id=batch.id,
            status=status.value,
            blocked=blocked,
            required_since=envelope.occurred_at,
            last_event_at=envelope.occurred_at,
            source_states=source_states,
            reasons=[reason],
            revision=1,
        )
        session.add(review)
    else:
        review.status = status.value
        review.blocked = blocked
        review.last_event_at = max(review.last_event_at, envelope.occurred_at)
        review.source_states = source_states
        review.reasons = [*review.reasons, reason]
        review.revision += 1
    await session.flush()
    event_type = _result_event_type(status)
    snapshot = _review_snapshot(review)
    await AuditService().record(
        session,
        AuditEvent(
            actor_user_id=_actor_id(envelope.payload),
            company_id=batch.company_id,
            branch_id=None,
            module="finance",
            entity_type="payment_batch",
            entity_id=batch.id,
            operation=event_type,
            request_id=envelope.request_id,
            correlation_id=envelope.correlation_id,
            before_snapshot=previous,
            after_snapshot=snapshot,
            reason_code=envelope.message_type,
        ),
    )
    outgoing = MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=event_type,
        event_version=1,
        producer_module="finance",
        producer_domain="treasury",
        aggregate_type="payment_batch",
        aggregate_id=batch.id,
        aggregate_version=batch.version,
        company_id=batch.company_id,
        branch_id=None,
        correlation_id=envelope.correlation_id,
        causation_id=envelope.message_id,
        request_id=envelope.request_id,
        payload={
            **snapshot,
            "source_module": envelope.producer_module,
            "source_type": envelope.aggregate_type,
            "source_id": str(envelope.aggregate_id),
            "source_version": envelope.aggregate_version,
            "source_event": envelope.message_type,
        },
    )
    await OutboxService().enqueue(session, outgoing)
    return outgoing.message_id


def _merged_status(
    source_states: dict[str, Any],
) -> tuple[TreasuryReviewStatus, bool]:
    active = [value for value in source_states.values() if value.get("blocked") is True]
    if not active:
        return TreasuryReviewStatus.CLEARED, False
    if any(value.get("status") == TreasuryReviewStatus.BLOCKED.value for value in active):
        return TreasuryReviewStatus.BLOCKED, True
    return TreasuryReviewStatus.REVIEW_REQUIRED, True


def _result_event_type(status: TreasuryReviewStatus) -> str:
    if status is TreasuryReviewStatus.BLOCKED:
        return PAYMENT_BATCH_BLOCKED
    if status is TreasuryReviewStatus.REVIEW_REQUIRED:
        return PAYMENT_BATCH_REEVALUATION_REQUESTED
    return PAYMENT_BATCH_REEVALUATION_CLEARED


def _review_snapshot(review: PaymentBatchReviewModel) -> dict[str, object]:
    return {
        "payment_batch_id": str(review.payment_batch_id),
        "review_status": review.status,
        "blocked": review.blocked,
        "revision": review.revision,
        "required_since": review.required_since.isoformat(),
        "last_event_at": review.last_event_at.isoformat(),
        "source_states": review.source_states,
    }


def _cursor_assessment(cursor: TreasurySourceCursorModel) -> TreasuryAssessment:
    raw = cursor.payload.get("_treasury_assessment")
    if not isinstance(raw, dict):
        raise RuntimeError("Treasury source cursor has no assessment metadata.")
    try:
        blocked = raw["blocked"]
        if type(blocked) is not bool:
            raise TypeError("blocked must be boolean")
        return TreasuryAssessment(
            status=TreasuryReviewStatus(str(raw["status"])),
            blocked=blocked,
            reason=str(raw["reason"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("Treasury source cursor assessment is invalid.") from error


def _cursor_envelope(cursor: TreasurySourceCursorModel) -> MessageEnvelope:
    payload = dict(cursor.payload)
    payload.pop("_treasury_assessment", None)
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
        payload=payload,
    )


def _actor_id(payload: dict[str, Any]) -> UUID | None:
    for field in ("actor_id", "updated_by", "decided_by"):
        value = _optional_payload_uuid(payload, field)
        if value is not None:
            return value
    return None


def _payload_uuid(payload: dict[str, Any], field: str) -> UUID:
    value = _optional_payload_uuid(payload, field)
    if value is None:
        raise ValueError(f"Treasury source event requires a valid {field}.")
    return value


def _optional_payload_uuid(payload: dict[str, Any], field: str) -> UUID | None:
    raw = payload.get(field)
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Treasury source event requires a valid {field}.") from error


__all__ = [
    "PAYMENT_BATCH_BLOCKED",
    "PAYMENT_BATCH_REEVALUATION_CLEARED",
    "PAYMENT_BATCH_REEVALUATION_REQUESTED",
    "TreasuryAssessment",
    "TreasuryReviewStatus",
    "accept_treasury_source_cursor",
    "apply_treasury_source_cursors",
    "reassess_impacted_payment_batches",
    "require_payment_batch_unblocked",
]
