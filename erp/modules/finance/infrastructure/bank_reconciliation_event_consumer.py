"""Inbox-backed consumer for event-driven bank reconciliation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import BankCandidateSource
from erp.modules.finance.domain import BankMovementDirection
from erp.modules.finance.infrastructure.bank_reconciliation_event_state import (
    BankCandidateProjection,
    accept_bank_reconciliation_cursor,
    deactivate_event_candidate,
    flag_reversed_reconciliations,
    reevaluate_pending_statements,
    upsert_event_candidate,
)
from erp.platform.database import Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope, MessageKind

BANK_RECONCILIATION_EVENT_CONSUMER = "finance.bank-reconciliation-source-events.v1"


@dataclass(frozen=True, slots=True)
class _EventPolicy:
    producer_module: str
    producer_domain: str
    aggregate_type: str
    candidate_source: BankCandidateSource | None = None
    direction: BankMovementDirection | None = None
    reversal: bool = False


_SUPPORTED_EVENTS = {
    "PaymentBatchConfirmed": _EventPolicy("finance", "treasury", "payment_batch"),
    "PayableInstallmentSettled": _EventPolicy(
        "finance",
        "finance",
        "payable_installment",
        BankCandidateSource.TREASURY_M12,
        BankMovementDirection.DEBIT,
    ),
    "ReceivableInstallmentSettled": _EventPolicy(
        "finance",
        "receivables",
        "receivable_installment",
        BankCandidateSource.RECEIVABLE_M13,
        BankMovementDirection.CREDIT,
    ),
    "BankSettlementReversed": _EventPolicy(
        "finance",
        "treasury",
        "payment_batch",
        reversal=True,
    ),
    "ReceivableSettlementReversed": _EventPolicy(
        "finance",
        "receivables",
        "receivable_installment",
        reversal=True,
    ),
}


class BankReconciliationEventConsumer:
    """Process neighboring settlement facts exactly once and re-evaluate pending movements."""

    def __init__(self, database: Database, inbox: InboxService | None = None) -> None:
        self._database = database
        self._inbox = inbox or InboxService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        policy = _validate_envelope(envelope)
        projection = _projection(envelope, policy)
        reversed_reference = _reversed_reference(envelope, policy)

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            if not await accept_bank_reconciliation_cursor(session, message):
                return
            if projection is not None:
                await upsert_event_candidate(session, message, projection)
            if reversed_reference is not None:
                await deactivate_event_candidate(session, message, reversed_reference)
                await flag_reversed_reconciliations(session, message, reversed_reference)
            await reevaluate_pending_statements(session, message)

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=BANK_RECONCILIATION_EVENT_CONSUMER,
                envelope=envelope,
                effect=effect,
            )


def _validate_envelope(envelope: MessageEnvelope) -> _EventPolicy:
    policy = _SUPPORTED_EVENTS.get(envelope.message_type)
    if (
        policy is None
        or envelope.message_kind is not MessageKind.DOMAIN_EVENT
        or envelope.event_version != 1
        or envelope.company_id is None
        or envelope.aggregate_version is None
        or envelope.producer_module != policy.producer_module
        or envelope.producer_domain != policy.producer_domain
        or envelope.aggregate_type != policy.aggregate_type
        or envelope.occurred_at.tzinfo is None
        or envelope.occurred_at.utcoffset() is None
    ):
        raise ValueError("Unsupported bank-reconciliation source event envelope.")
    payload_company = envelope.payload.get("company_id")
    if payload_company is not None and str(payload_company) != str(envelope.company_id):
        raise ValueError("Bank-reconciliation source event crosses the company boundary.")
    return policy


def _projection(
    envelope: MessageEnvelope,
    policy: _EventPolicy,
) -> BankCandidateProjection | None:
    if policy.candidate_source is None:
        return None
    assert policy.direction is not None
    return BankCandidateProjection(
        reference_id=_payload_uuid(envelope, "reference_id", default=envelope.aggregate_id),
        source=policy.candidate_source,
        expected_on=_payload_date(envelope, "settled_on"),
        amount=_payload_amount(envelope, "amount"),
        direction=policy.direction,
        document_number=_optional_payload_text(envelope, "document_number"),
    )


def _reversed_reference(
    envelope: MessageEnvelope,
    policy: _EventPolicy,
) -> UUID | None:
    if not policy.reversal:
        return None
    return _payload_uuid(envelope, "reference_id")


def _payload_uuid(
    envelope: MessageEnvelope,
    field: str,
    *,
    default: UUID | None = None,
) -> UUID:
    value = envelope.payload.get(field, default)
    try:
        parsed = UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Bank-reconciliation event requires a valid {field}.") from error
    if parsed.int == 0:
        raise ValueError(f"Bank-reconciliation event requires a valid {field}.")
    return parsed


def _payload_date(envelope: MessageEnvelope, field: str) -> date:
    try:
        return date.fromisoformat(str(envelope.payload[field]))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Bank-reconciliation event requires a valid {field}.") from error


def _payload_amount(envelope: MessageEnvelope, field: str) -> Decimal:
    try:
        value = Decimal(str(envelope.payload[field])).quantize(Decimal("0.01"))
    except (KeyError, InvalidOperation) as error:
        raise ValueError(f"Bank-reconciliation event requires a valid {field}.") from error
    if not value.is_finite() or value <= 0:
        raise ValueError(f"Bank-reconciliation event requires a positive {field}.")
    return value


def _optional_payload_text(envelope: MessageEnvelope, field: str) -> str | None:
    value = envelope.payload.get(field)
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    if not normalized or len(normalized) > 120:
        raise ValueError(f"Bank-reconciliation event requires a valid {field}.")
    return normalized


__all__ = [
    "BANK_RECONCILIATION_EVENT_CONSUMER",
    "BankReconciliationEventConsumer",
]
