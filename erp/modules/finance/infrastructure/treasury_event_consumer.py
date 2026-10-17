"""Inbox-backed consumer for facts that can invalidate Treasury batches."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.infrastructure.treasury_event_state import (
    TreasuryAssessment,
    TreasuryReviewStatus,
    accept_treasury_source_cursor,
    reassess_impacted_payment_batches,
)
from erp.platform.database import Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope, MessageKind

TREASURY_EVENT_CONSUMER = "finance.treasury-source-events.v1"


@dataclass(frozen=True, slots=True)
class _EventPolicy:
    producer_module: str
    producer_domain: str
    aggregate_type: str


_SUPPORTED_EVENTS = {
    "PayableAdjusted": _EventPolicy("finance", "finance", "payable"),
    "PayableApproved": _EventPolicy("finance", "finance", "payable"),
    "PayableRejected": _EventPolicy("finance", "finance", "payable"),
    "PayableCancelled": _EventPolicy("finance", "finance", "payable"),
    "MatchingSessionCompleted": _EventPolicy(
        "procurement", "procurement", "three_way_match_session"
    ),
    "MatchingDiscrepancyDetected": _EventPolicy(
        "procurement", "procurement", "three_way_match_session"
    ),
    "MatchingOverrideApproved": _EventPolicy(
        "procurement", "procurement", "three_way_match_session"
    ),
    "MatchingOverrideRejected": _EventPolicy(
        "procurement", "procurement", "three_way_match_session"
    ),
    "FiscalReceivingReconciled": _EventPolicy(
        "fiscal", "fiscal", "fiscal_receiving_reconciliation"
    ),
    "ApprovalDecisionMade": _EventPolicy("workflow", "workflow", "workflow_instance"),
}


class TreasuryEventConsumer:
    """Consume neighboring-domain facts exactly once and reassess mutable batches."""

    def __init__(self, database: Database, inbox: InboxService | None = None) -> None:
        self._database = database
        self._inbox = inbox or InboxService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        _validate_envelope(envelope)
        assessment = _assessment(envelope)

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            accepted = await accept_treasury_source_cursor(
                session,
                message,
                assessment,
            )
            if not accepted:
                return
            await reassess_impacted_payment_batches(session, message, assessment)

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=TREASURY_EVENT_CONSUMER,
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
        raise ValueError("Unsupported Treasury source event envelope.")
    payload_company = envelope.payload.get("company_id")
    if payload_company is not None and str(payload_company) != str(envelope.company_id):
        raise ValueError("Treasury source event crosses the company boundary.")
    if envelope.message_type == "ApprovalDecisionMade" and (
        envelope.payload.get("source_module") != "finance"
        or envelope.payload.get("source_type") != "PAYMENT_BATCH"
    ):
        raise ValueError("Approval decision does not target a Treasury payment batch.")
    return policy


def _assessment(envelope: MessageEnvelope) -> TreasuryAssessment:
    event_type = envelope.message_type
    if event_type == "PayableAdjusted":
        return _review("Payable values changed after batch composition.")
    if event_type in {"PayableRejected", "PayableCancelled"}:
        return _blocked(f"{event_type} invalidates payment eligibility.")
    if event_type == "PayableApproved":
        return _cleared("Payable approval restored payment eligibility.")
    if event_type == "MatchingDiscrepancyDetected":
        return _blocked("Three-way matching reported an unresolved discrepancy.")
    if event_type == "MatchingOverrideApproved":
        return _cleared("Approved matching override restored payment eligibility.")
    if event_type == "MatchingOverrideRejected":
        return _blocked("Rejected matching override keeps the batch ineligible.")
    if event_type == "MatchingSessionCompleted":
        status = str(envelope.payload.get("report_status", envelope.payload.get("status", "")))
        if status in {"MATCHED", "OVERRIDDEN"}:
            return _cleared("Three-way matching completed without an active discrepancy.")
        return _blocked("Three-way matching completed with discrepancies.")
    if event_type == "FiscalReceivingReconciled":
        financial = _payload_bool(envelope, "financial_blocked")
        physical = _payload_bool(envelope, "physical_pending")
        if financial:
            return _blocked("Fiscal reconciliation blocks financial release.")
        if physical:
            return _review("Physical reconciliation remains pending.")
        return _cleared("Fiscal and physical reconciliation is clear.")
    if event_type == "ApprovalDecisionMade":
        decision = str(envelope.payload.get("decision", ""))
        if decision == "APPROVED":
            return _cleared("M22 approved the payment-batch request.")
        if decision == "REJECTED":
            return _blocked("M22 rejected the payment-batch request.")
        raise ValueError("Treasury approval decision must be APPROVED or REJECTED.")
    raise ValueError("Unsupported Treasury assessment event.")


def _payload_bool(envelope: MessageEnvelope, field: str) -> bool:
    value = envelope.payload.get(field)
    if type(value) is not bool:
        raise ValueError(f"Treasury source event requires a boolean {field}.")
    return value


def _blocked(reason: str) -> TreasuryAssessment:
    return TreasuryAssessment(TreasuryReviewStatus.BLOCKED, True, reason)


def _review(reason: str) -> TreasuryAssessment:
    return TreasuryAssessment(TreasuryReviewStatus.REVIEW_REQUIRED, True, reason)


def _cleared(reason: str) -> TreasuryAssessment:
    return TreasuryAssessment(TreasuryReviewStatus.CLEARED, False, reason)


__all__ = ["TREASURY_EVENT_CONSUMER", "TreasuryEventConsumer"]
