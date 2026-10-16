"""Inbox-backed consumer for upstream facts that can stale matching snapshots."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.infrastructure.matching_event_state import (
    MatchingSourceReference,
    accept_source_cursor,
    flag_impacted_matching_sessions,
)
from erp.platform.database import Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope, MessageKind

MATCHING_EVENT_CONSUMER = "procurement.matching-source-events.v1"


@dataclass(frozen=True, slots=True)
class _EventPolicy:
    producer_module: str
    aggregate_type: str
    invalidates_snapshot: bool = False
    derived_references: bool = False


_SUPPORTED_EVENTS = {
    "PurchaseOrderApproved": _EventPolicy("procurement", "purchase_order"),
    "PurchaseOrderRejected": _EventPolicy("procurement", "purchase_order", True),
    "PurchaseOrderCancelled": _EventPolicy("procurement", "purchase_order", True),
    "GoodsReceiptCreated": _EventPolicy("procurement", "goods_receipt"),
    "GoodsReceiptReceived": _EventPolicy("procurement", "goods_receipt"),
    "GoodsReceiptInspected": _EventPolicy("procurement", "goods_receipt"),
    "GoodsReceiptPosted": _EventPolicy("procurement", "goods_receipt"),
    "InboundFiscalDocumentManifested": _EventPolicy(
        "fiscal", "inbound_fiscal_document"
    ),
    "InboundFiscalDocumentCancelled": _EventPolicy(
        "fiscal", "inbound_fiscal_document", True
    ),
    "FiscalReceivingReconciled": _EventPolicy(
        "fiscal", "fiscal_receiving_reconciliation", derived_references=True
    ),
    "ProvisionalFinancialEntryConverted": _EventPolicy(
        "finance", "provisional_financial_entry"
    ),
    "ProvisionalFinancialEntryVoided": _EventPolicy(
        "finance", "provisional_financial_entry", True
    ),
    "PayableApprovalRequested": _EventPolicy("finance", "payable"),
    "PayableApproved": _EventPolicy("finance", "payable"),
    "PayableRejected": _EventPolicy("finance", "payable", True),
    "PayableScheduled": _EventPolicy("finance", "payable"),
    "PayableAdjusted": _EventPolicy("finance", "payable"),
}


class MatchingEventConsumer:
    """Consume M6/M11/M12 facts exactly once and queue stale sessions."""

    def __init__(self, database: Database, inbox: InboxService | None = None) -> None:
        self._database = database
        self._inbox = inbox or InboxService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        policy = _validate_envelope(envelope)

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            accepted = await accept_source_cursor(
                session,
                message,
                invalidates_snapshot=policy.invalidates_snapshot,
            )
            if not accepted:
                return
            await flag_impacted_matching_sessions(
                session,
                message,
                invalidates_snapshot=policy.invalidates_snapshot,
                references=_references(message, policy),
            )

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=MATCHING_EVENT_CONSUMER,
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
        or envelope.producer_domain != policy.producer_module
        or envelope.aggregate_type != policy.aggregate_type
        or envelope.occurred_at.tzinfo is None
        or envelope.occurred_at.utcoffset() is None
    ):
        raise ValueError("Unsupported matching source event envelope.")
    payload_company = envelope.payload.get("company_id")
    if payload_company is not None and str(payload_company) != str(envelope.company_id):
        raise ValueError("Matching source event crosses the company boundary.")
    return policy


def _references(
    envelope: MessageEnvelope,
    policy: _EventPolicy,
) -> tuple[MatchingSourceReference, ...]:
    if not policy.derived_references:
        return (
            MatchingSourceReference(
                producer_module=policy.producer_module,
                aggregate_type=policy.aggregate_type,
                aggregate_id=envelope.aggregate_id,
                captured_version=envelope.aggregate_version,
            ),
        )
    return (
        MatchingSourceReference(
            "procurement",
            "purchase_order",
            _payload_uuid(envelope, "purchase_order_id"),
            None,
        ),
        MatchingSourceReference(
            "procurement",
            "goods_receipt",
            _payload_uuid(envelope, "goods_receipt_id"),
            None,
        ),
        MatchingSourceReference(
            "fiscal",
            "inbound_fiscal_document",
            _payload_uuid(envelope, "inbound_fiscal_document_id"),
            None,
        ),
    )


def _payload_uuid(envelope: MessageEnvelope, field: str) -> UUID:
    try:
        return UUID(str(envelope.payload[field]))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Matching source event requires a valid {field}.") from error


__all__ = ["MATCHING_EVENT_CONSUMER", "MatchingEventConsumer"]
