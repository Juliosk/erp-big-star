"""Consolidated M6 -> M11 -> M22 -> M12 payable journey."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from erp.apps.api.finance_workflow import M22PayableApprovalGateway
from erp.modules.finance.application import ChangePayable, PayableCommandMetadata
from erp.modules.finance.domain import (
    PayableApprovalStatus,
    PayableStatus,
    ProvisionalEntryOrigin,
    ProvisionalEntryStatus,
    SegregationOfDutiesViolation,
)
from erp.modules.finance.infrastructure import (
    FINANCE_APPROVAL_CONSUMER,
    FINANCE_DIVERGENCE_CONSUMER,
    FINANCE_PAYABLE_PROVISIONING_CONSUMER,
    PURCHASE_ORDER_APPROVED,
    FiscalEventConsumer,
    PayableApprovalDecisionConsumer,
    PayableDivergenceConsumer,
    PayableGovernanceRepository,
    PayableRepository,
    PostgresPayableStore,
    ProvisionalEntryRepository,
)
from erp.modules.workflow.domain import ApprovalMode, WorkflowDefinition, WorkflowStepDefinition
from erp.modules.workflow.infrastructure import WorkflowRepository
from erp.platform.audit import AuditEventModel
from erp.platform.errors import ApplicationError
from erp.platform.inbox import InboxEventModel
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_payable_approval_governance import governance_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


@asynccontextmanager
async def finance_e2e_fixture() -> AsyncIterator[ProcurementFixture]:
    async with governance_fixture() as data:
        try:
            yield data
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(InboxEventModel).where(
                        InboxEventModel.consumer_name == FINANCE_PAYABLE_PROVISIONING_CONSUMER
                    )
                )


def _purchase_approved_event(data: ProcurementFixture) -> MessageEnvelope:
    order_id = uuid4()
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=PURCHASE_ORDER_APPROVED,
        event_version=1,
        producer_module="procurement",
        producer_domain="procurement",
        aggregate_type="purchase_order",
        aggregate_id=order_id,
        aggregate_version=3,
        company_id=data.company_id,
        branch_id=None,
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        payload={
            "company_id": str(data.company_id),
            "source_id": str(order_id),
            "requested_by": str(data.actor_id),
            "supplier_id": str(uuid4()),
            "supplier_tax_id": "12345678000195",
            "document_number": f"PO-E2E-{uuid4().hex[:10]}",
            "amount": "123.40",
            "currency": "BRL",
            "installment_days": [30],
        },
    )


def _reconciliation_event(
    data: ProcurementFixture,
    *,
    purchase_order_id: UUID,
    financial_blocked: bool,
    physical_pending: bool,
) -> MessageEnvelope:
    reconciliation_id = uuid4()
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type="FiscalReceivingReconciled",
        event_version=1,
        producer_module="fiscal",
        producer_domain="fiscal",
        aggregate_type="fiscal_receiving_reconciliation",
        aggregate_id=reconciliation_id,
        aggregate_version=1,
        company_id=data.company_id,
        branch_id=None,
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        payload={
            "reconciliation_id": str(reconciliation_id),
            "purchase_order_id": str(purchase_order_id),
            "financial_blocked": financial_blocked,
            "physical_pending": physical_pending,
        },
    )


async def _approval_policy(data: ProcurementFixture) -> None:
    definition = WorkflowDefinition.create(
        company_id=data.company_id,
        code=f"PAYABLE-E2E-{uuid4().hex[:8]}",
        name="Alçada financeira consolidada",
        source_module="FINANCE",
        source_type="PAYABLE",
        approval_mode=ApprovalMode.SEQUENTIAL,
    )
    step = WorkflowStepDefinition.create(
        company_id=data.company_id,
        sequence=1,
        code="FINANCE_MANAGER",
        name="Gerência financeira",
        required_permission="finance.payable.approve",
        threshold_amount=Decimal("100.00"),
    )
    async with data.database.session() as session, session.begin():
        await WorkflowRepository(session, company_id=data.company_id).add_definition(
            definition, steps=(step,), actor_id=data.actor_id
        )


def _approval_event(
    data: ProcurementFixture,
    *,
    payable_id: UUID,
    workflow_id: UUID,
    approver_id: UUID,
) -> MessageEnvelope:
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type="ApprovalDecisionMade",
        event_version=1,
        producer_module="workflow",
        producer_domain="workflow",
        aggregate_type="workflow_instance",
        aggregate_id=workflow_id,
        aggregate_version=2,
        company_id=data.company_id,
        branch_id=None,
        correlation_id=uuid4(),
        request_id=uuid4(),
        causation_id=uuid4(),
        payload={
            "source_module": "finance",
            "source_type": "PAYABLE",
            "source_id": str(payable_id),
            "decision": "APPROVED",
            "decided_by": str(approver_id),
            "workflow_instance_id": str(workflow_id),
        },
    )


def test_purchase_reconciliation_workflow_and_payable_are_traceable() -> None:
    async def scenario() -> None:
        async with finance_e2e_fixture() as data:
            purchase_event = _purchase_approved_event(data)
            provisioning = FiscalEventConsumer(data.database)
            provisioned = await provisioning.consume(purchase_event)
            provision_replay = await provisioning.consume(purchase_event)
            assert provisioned.processed
            assert provision_replay.duplicate

            async with data.database.session() as session:
                provision = await ProvisionalEntryRepository(
                    session, company_id=data.company_id
                ).get_by_source_id(
                    origin=ProvisionalEntryOrigin.APPROVED_PURCHASE_ORDER,
                    source_id=purchase_event.aggregate_id,
                )
                assert provision is not None
                assert provision.status is ProvisionalEntryStatus.CONVERTED
                assert provision.payable_id is not None
                payable_id = provision.payable_id
                payable = await PayableRepository(session, company_id=data.company_id).get(
                    payable_id
                )
                assert payable is not None
                assert payable.status is PayableStatus.DRAFT
                assert payable.total_amount == Decimal("123.40")
                cross_tenant = await PayableRepository(
                    session, company_id=data.other_company_id
                ).get(payable_id)
                assert cross_tenant is None

            divergence = PayableDivergenceConsumer(data.database)
            blocked_event = _reconciliation_event(
                data,
                purchase_order_id=purchase_event.aggregate_id,
                financial_blocked=True,
                physical_pending=True,
            )
            blocked_result = await divergence.consume(blocked_event)
            blocked_replay = await divergence.consume(blocked_event)
            assert blocked_result.processed
            assert blocked_replay.duplicate

            async with data.database.session() as session:
                blocked = await PayableGovernanceRepository(
                    session, company_id=data.company_id
                ).get(payable_id)
                current = await PayableRepository(session, company_id=data.company_id).get(
                    payable_id
                )
                assert blocked is not None
                assert blocked.fiscal_blocked
                assert current is not None

            store = PostgresPayableStore(
                data.database,
                ttl_seconds=3600,
                approval_gateway=M22PayableApprovalGateway(),
            )
            with pytest.raises(ApplicationError) as divergence_error:
                await store.submit(
                    ChangePayable(
                        data.company_id,
                        payable_id,
                        current.version,
                        PayableCommandMetadata(uuid4(), uuid4()),
                    ),
                    actor_id=data.actor_id,
                    granted_permissions=frozenset({"finance.payable.approve"}),
                )
            assert divergence_error.value.code == "PAYABLE_DIVERGENCE_BLOCKED"

            cleared_event = _reconciliation_event(
                data,
                purchase_order_id=purchase_event.aggregate_id,
                financial_blocked=False,
                physical_pending=False,
            )
            assert (await divergence.consume(cleared_event)).processed
            await _approval_policy(data)
            async with data.database.session() as session:
                current = await PayableRepository(session, company_id=data.company_id).get(
                    payable_id
                )
                assert current is not None
            submitted = await store.submit(
                ChangePayable(
                    data.company_id,
                    payable_id,
                    current.version,
                    PayableCommandMetadata(uuid4(), uuid4()),
                ),
                actor_id=data.actor_id,
                granted_permissions=frozenset({"finance.payable.approve"}),
            )
            assert submitted.status is PayableStatus.PENDING_APPROVAL

            async with data.database.session() as session:
                governance = await PayableGovernanceRepository(
                    session, company_id=data.company_id
                ).get(payable_id)
                assert governance is not None
                assert governance.approval_status is PayableApprovalStatus.PENDING
                assert governance.workflow_instance_id is not None
                workflow_id = governance.workflow_instance_id

            approvals = PayableApprovalDecisionConsumer(data.database)
            with pytest.raises(SegregationOfDutiesViolation):
                await approvals.consume(
                    _approval_event(
                        data,
                        payable_id=payable_id,
                        workflow_id=workflow_id,
                        approver_id=data.actor_id,
                    )
                )
            approver_id = uuid4()
            decision = _approval_event(
                data,
                payable_id=payable_id,
                workflow_id=workflow_id,
                approver_id=approver_id,
            )
            approved_result = await approvals.consume(decision)
            approved_replay = await approvals.consume(decision)
            assert approved_result.processed
            assert approved_replay.duplicate

            async with data.database.session() as session:
                payable = await PayableRepository(session, company_id=data.company_id).get(
                    payable_id
                )
                governance = await PayableGovernanceRepository(
                    session, company_id=data.company_id
                ).get(payable_id)
                assert payable is not None
                assert payable.status is PayableStatus.APPROVED
                assert payable.decision_by == approver_id
                assert governance is not None
                assert not governance.blocked
                assert governance.approval_status is PayableApprovalStatus.APPROVED

                operations = set(
                    await session.scalars(
                        select(AuditEventModel.operation).where(
                            AuditEventModel.company_id == data.company_id,
                            AuditEventModel.module == "finance",
                            AuditEventModel.entity_id == payable_id,
                        )
                    )
                )
                assert {
                    "PAYABLE_DIVERGENCE_BLOCKED",
                    "PAYABLE_DIVERGENCE_CLEARED",
                    "PAYABLE_APPROVAL_REQUESTED",
                    "PAYABLE_APPROVED",
                } <= operations
                event_types = set(
                    await session.scalars(
                        select(OutboxEventModel.event_type).where(
                            OutboxEventModel.aggregate_id == payable_id,
                            OutboxEventModel.source_module == "finance",
                        )
                    )
                )
                assert {
                    "PayableDivergenceBlocked",
                    "PayableDivergenceCleared",
                    "PayableApprovalRequested",
                    "PayableApproved",
                } <= event_types
                inbox_count = len(
                    tuple(
                        await session.scalars(
                            select(InboxEventModel).where(
                                InboxEventModel.consumer_name.in_(
                                    (
                                        FINANCE_PAYABLE_PROVISIONING_CONSUMER,
                                        FINANCE_DIVERGENCE_CONSUMER,
                                        FINANCE_APPROVAL_CONSUMER,
                                    )
                                ),
                                InboxEventModel.event_id.in_(
                                    (
                                        purchase_event.message_id,
                                        blocked_event.message_id,
                                        cleared_event.message_id,
                                        decision.message_id,
                                    )
                                ),
                            )
                        )
                    )
                )
                assert inbox_count == 4

    asyncio.run(scenario())


def test_finance_runbook_preserves_sprint_17_scope() -> None:
    content = Path("docs/finance-runbook.md").read_text(encoding="utf-8")
    assert "SOD_VIOLATION" in content
    assert "PAYABLE_DIVERGENCE_BLOCKED" in content
    assert "finance.payable-approval.v1" in content
    assert "Liquidação bancária" in content
    assert "Three-Way Match" in content
