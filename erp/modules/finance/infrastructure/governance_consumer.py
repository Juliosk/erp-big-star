"""Inbox consumers for M12 divergence facts and M22 approval decisions."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import ChangePayable, PayableCommandMetadata
from erp.modules.finance.domain import PayableSegregationPolicy, PayableStatus
from erp.modules.finance.infrastructure.payable_governance_repository import (
    PayableGovernanceRepository,
)
from erp.modules.finance.infrastructure.payable_model import ProvisionalEntryModel
from erp.modules.finance.infrastructure.payable_repository import PayableRepository
from erp.modules.finance.infrastructure.payable_store import _enqueue, _snapshot
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.database import Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope

APPROVAL_DECISION_MADE = "ApprovalDecisionMade"
FISCAL_RECEIVING_RECONCILED = "FiscalReceivingReconciled"
FINANCE_APPROVAL_CONSUMER = "finance.payable-approval.v1"
FINANCE_DIVERGENCE_CONSUMER = "finance.payable-divergence.v1"


class PayableApprovalDecisionConsumer:
    def __init__(self, database: Database, inbox: InboxService | None = None) -> None:
        self._database = database
        self._inbox = inbox or InboxService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        _require_envelope(envelope, APPROVAL_DECISION_MADE, "workflow")

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            if (
                message.payload.get("source_module") != "finance"
                or message.payload.get("source_type") != "PAYABLE"
            ):
                raise ValueError("Approval decision does not target an M12 payable.")
            company_id = _company(message)
            payable_id = _uuid(message, "source_id")
            workflow_id = _uuid(message, "workflow_instance_id")
            actor_id = _uuid(message, "decided_by")
            repository = PayableRepository(session, company_id=company_id)
            current = await repository.get(payable_id)
            if current is None:
                raise ValueError("Payable targeted by approval was not found.")
            if current.status in {PayableStatus.APPROVED, PayableStatus.REJECTED}:
                return
            governance_repository = PayableGovernanceRepository(session, company_id=company_id)
            governance = await governance_repository.get(payable_id, for_update=True)
            if governance is None:
                raise ValueError("Payable governance record was not found.")
            governance.require_unblocked()
            decision = message.payload.get("decision")
            if decision == "APPROVED":
                changed = current.approve(
                    approver_id=actor_id,
                    policy=PayableSegregationPolicy(governance.sod_threshold),
                )
                event_type = "PayableApproved"
                operation = "PAYABLE_APPROVED"
            elif decision == "REJECTED":
                changed = current.reject(
                    rejected_by=actor_id,
                    reason="Rejected by the corporate approval workflow.",
                )
                event_type = "PayableRejected"
                operation = "PAYABLE_REJECTED"
            else:
                raise ValueError("Approval decision must be APPROVED or REJECTED.")
            await repository.save(changed, actor_id=actor_id, expected_version=current.version)
            governed = governance.decide(
                approved=decision == "APPROVED", workflow_instance_id=workflow_id
            )
            await governance_repository.save(
                governed, actor_id=actor_id, expected_version=governance.version
            )
            await AuditService().record(
                session,
                AuditEvent(
                    actor_user_id=actor_id,
                    company_id=company_id,
                    branch_id=None,
                    module="finance",
                    entity_type="payable",
                    entity_id=payable_id,
                    operation=operation,
                    request_id=message.request_id,
                    correlation_id=message.correlation_id,
                    before_snapshot=_snapshot(current),
                    after_snapshot={
                        **_snapshot(changed),
                        "workflow_instance_id": str(workflow_id),
                    },
                ),
            )
            await _enqueue(
                session,
                payable=changed,
                event_type=event_type,
                command=ChangePayable(
                    company_id=company_id,
                    payable_id=payable_id,
                    expected_version=current.version,
                    metadata=PayableCommandMetadata(message.request_id, message.correlation_id),
                ),
                causation_id=message.message_id,
                extra={"workflow_instance_id": str(workflow_id)},
            )

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=FINANCE_APPROVAL_CONSUMER,
                envelope=envelope,
                effect=effect,
            )


class PayableDivergenceConsumer:
    def __init__(self, database: Database, inbox: InboxService | None = None) -> None:
        self._database = database
        self._inbox = inbox or InboxService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        _require_envelope(envelope, FISCAL_RECEIVING_RECONCILED, "fiscal")

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            company_id = _company(message)
            purchase_order_id = _uuid(message, "purchase_order_id")
            fiscal_blocked = _boolean(message, "financial_blocked")
            purchasing_blocked = _boolean(message, "physical_pending")
            payable_ids = tuple(
                await session.scalars(
                    select(ProvisionalEntryModel.payable_id).where(
                        ProvisionalEntryModel.company_id == company_id,
                        ProvisionalEntryModel.origin == "APPROVED_PURCHASE_ORDER",
                        ProvisionalEntryModel.source_id == purchase_order_id,
                        ProvisionalEntryModel.payable_id.is_not(None),
                    )
                )
            )
            for payable_id in payable_ids:
                if payable_id is None:
                    continue
                repository = PayableGovernanceRepository(session, company_id=company_id)
                current = await repository.get_or_create(payable_id, actor_id=message.message_id)
                changed = current.apply_divergence(
                    fiscal_blocked=fiscal_blocked,
                    purchasing_blocked=purchasing_blocked,
                )
                await repository.save(
                    changed,
                    actor_id=message.message_id,
                    expected_version=current.version,
                )
                snapshot = {
                    "fiscal_blocked": changed.fiscal_blocked,
                    "purchasing_blocked": changed.purchasing_blocked,
                    "reconciliation_id": str(message.payload.get("reconciliation_id")),
                }
                await AuditService().record(
                    session,
                    AuditEvent(
                        actor_user_id=None,
                        company_id=company_id,
                        branch_id=None,
                        module="finance",
                        entity_type="payable",
                        entity_id=payable_id,
                        operation=(
                            "PAYABLE_DIVERGENCE_BLOCKED"
                            if changed.blocked
                            else "PAYABLE_DIVERGENCE_CLEARED"
                        ),
                        request_id=message.request_id,
                        correlation_id=message.correlation_id,
                        after_snapshot=snapshot,
                    ),
                )
                payable = await PayableRepository(session, company_id=company_id).get(payable_id)
                if payable is None:
                    raise ValueError("Governed payable was not found.")
                await _enqueue(
                    session,
                    payable=payable,
                    event_type=(
                        "PayableDivergenceBlocked"
                        if changed.blocked
                        else "PayableDivergenceCleared"
                    ),
                    command=ChangePayable(
                        company_id=company_id,
                        payable_id=payable_id,
                        expected_version=payable.version,
                        metadata=PayableCommandMetadata(message.request_id, message.correlation_id),
                    ),
                    causation_id=message.message_id,
                    extra=snapshot,
                )

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=FINANCE_DIVERGENCE_CONSUMER,
                envelope=envelope,
                effect=effect,
            )


def _require_envelope(envelope: MessageEnvelope, message_type: str, producer: str) -> None:
    if (
        envelope.message_type != message_type
        or envelope.event_version != 1
        or envelope.producer_module != producer
        or envelope.company_id is None
    ):
        raise ValueError("Unsupported payable governance envelope.")


def _company(message: MessageEnvelope) -> UUID:
    if message.company_id is None:
        raise ValueError("Governance event requires company_id.")
    return message.company_id


def _uuid(message: MessageEnvelope, field: str) -> UUID:
    try:
        return UUID(str(message.payload.get(field)))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Governance event requires a valid {field}.") from error


def _boolean(message: MessageEnvelope, field: str) -> bool:
    value = message.payload.get(field)
    if type(value) is not bool:
        raise ValueError(f"Governance event requires a boolean {field}.")
    return value


__all__ = [
    "FINANCE_APPROVAL_CONSUMER",
    "FINANCE_DIVERGENCE_CONSUMER",
    "PayableApprovalDecisionConsumer",
    "PayableDivergenceConsumer",
]
