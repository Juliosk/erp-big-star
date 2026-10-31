"""Inbox-backed consumer for event-driven Cash Flow recomposition."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.infrastructure.cash_flow_event_state import (
    CashFlowRecompositionWorker,
    accept_cash_flow_source_cursor,
    enqueue_cash_flow_recompositions,
)
from erp.platform.database import Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope, MessageKind

CASH_FLOW_EVENT_CONSUMER = "finance.cash-flow-source-events.v1"

_SUPPORTED_EVENTS = {
    "PayableApproved": ("finance", "finance", "payable"),
    "PayableScheduled": ("finance", "finance", "payable"),
    "PayableAdjusted": ("finance", "finance", "payable"),
    "PayableCancelled": ("finance", "finance", "payable"),
    "PayableInstallmentSettled": ("finance", "finance", "payable_installment"),
    "PaymentBatchApproved": ("finance", "treasury", "payment_batch"),
    "PaymentBatchReleased": ("finance", "treasury", "payment_batch"),
    "PaymentBatchSubmitted": ("finance", "treasury", "payment_batch"),
    "PaymentBatchConfirmed": ("finance", "treasury", "payment_batch"),
    "PaymentBatchFailed": ("finance", "treasury", "payment_batch"),
    "BankMovementReconciled": ("finance", "bank_reconciliation", "bank_movement"),
    "ReceivableInstallmentCreated": ("finance", "receivables", "receivable_installment"),
    "ReceivableInstallmentAdjusted": ("finance", "receivables", "receivable_installment"),
    "ReceivableInstallmentSettled": ("finance", "receivables", "receivable_installment"),
    "ReceivableSettlementReversed": ("finance", "receivables", "receivable_installment"),
}


class CashFlowEventConsumer:
    """Accept relevant tenant facts once and recompose affected projections."""

    def __init__(
        self,
        database: Database,
        *,
        inbox: InboxService | None = None,
        worker: CashFlowRecompositionWorker | None = None,
    ) -> None:
        self._database = database
        self._inbox = inbox or InboxService()
        self._worker = worker or CashFlowRecompositionWorker()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        _validate_envelope(envelope)

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            if not await accept_cash_flow_source_cursor(session, message):
                return
            await enqueue_cash_flow_recompositions(
                session,
                message,
                requested_at=datetime.now(UTC),
            )

        async with self._database.session() as session, session.begin():
            result = await self._inbox.process(
                session,
                consumer_name=CASH_FLOW_EVENT_CONSUMER,
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
        or (envelope.producer_module, envelope.producer_domain, envelope.aggregate_type) != policy
        or envelope.occurred_at.tzinfo is None
        or envelope.occurred_at.utcoffset() is None
    ):
        raise ValueError("Unsupported Cash Flow source event envelope.")
    payload_company = envelope.payload.get("company_id")
    if payload_company is not None and str(payload_company) != str(envelope.company_id):
        raise ValueError("Cash Flow source event crosses the company boundary.")


__all__ = ["CASH_FLOW_EVENT_CONSUMER", "CashFlowEventConsumer"]
