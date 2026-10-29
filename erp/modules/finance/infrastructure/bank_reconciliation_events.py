"""Transactional Outbox effects for reconciled bank movements."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import BankConciliationResult
from erp.modules.finance.domain import BankMovementStatus, BankStatement
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

BANK_MOVEMENT_RECONCILED = "BankMovementReconciled"
BANK_RECONCILIATION_REVIEW_REQUIRED = "BankReconciliationReviewRequired"


async def publish_reconciled_movements(
    session: AsyncSession,
    *,
    before: BankStatement,
    result: BankConciliationResult,
    request_id: UUID | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
) -> tuple[UUID, ...]:
    """Publish only movements that became reconciled in the current transaction."""
    previous = {movement.id: movement.status for movement in before.movements}
    event_ids = []
    for movement in result.statement.movements:
        if (
            movement.status is not BankMovementStatus.RECONCILED
            or previous.get(movement.id) is BankMovementStatus.RECONCILED
        ):
            continue
        assert movement.matched_reference_id is not None
        assert movement.reconciled_at is not None
        assert movement.match_score is not None
        envelope = MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=BANK_MOVEMENT_RECONCILED,
            event_version=1,
            producer_module="finance",
            producer_domain="bank_reconciliation",
            aggregate_type="bank_movement",
            aggregate_id=movement.id,
            aggregate_version=result.statement.version,
            company_id=result.statement.company_id,
            branch_id=None,
            correlation_id=correlation_id or uuid4(),
            causation_id=causation_id,
            request_id=request_id or uuid4(),
            payload={
                "company_id": str(result.statement.company_id),
                "bank_statement_id": str(result.statement.id),
                "bank_movement_id": str(movement.id),
                "bank_account_id": str(movement.bank_account_id),
                "booked_on": movement.booked_on.isoformat(),
                "amount": str(movement.amount),
                "direction": movement.direction.value,
                "kind": movement.kind.value,
                "document_number": movement.document_number,
                "matched_reference_id": str(movement.matched_reference_id),
                "match_score": str(movement.match_score),
                "reconciled_at": movement.reconciled_at.isoformat(),
            },
        )
        await OutboxService().enqueue(session, envelope)
        event_ids.append(envelope.message_id)
    return tuple(event_ids)


async def publish_reconciliation_review(
    session: AsyncSession,
    *,
    statement: BankStatement,
    movement_id: UUID,
    reference_id: UUID,
    request_id: UUID,
    correlation_id: UUID,
    causation_id: UUID,
    reason: str,
) -> UUID:
    envelope = MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=BANK_RECONCILIATION_REVIEW_REQUIRED,
        event_version=1,
        producer_module="finance",
        producer_domain="bank_reconciliation",
        aggregate_type="bank_statement",
        aggregate_id=statement.id,
        aggregate_version=statement.version,
        company_id=statement.company_id,
        branch_id=None,
        correlation_id=correlation_id,
        causation_id=causation_id,
        request_id=request_id,
        payload={
            "company_id": str(statement.company_id),
            "bank_statement_id": str(statement.id),
            "bank_movement_id": str(movement_id),
            "matched_reference_id": str(reference_id),
            "reason": reason,
        },
    )
    await OutboxService().enqueue(session, envelope)
    return envelope.message_id


__all__ = [
    "BANK_MOVEMENT_RECONCILED",
    "BANK_RECONCILIATION_REVIEW_REQUIRED",
    "publish_reconciled_movements",
    "publish_reconciliation_review",
]
