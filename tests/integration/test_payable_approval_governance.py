"""M12 fiscal blocks, M22 authority, SoD and atomic side effects."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from erp.apps.api.finance_workflow import M22PayableApprovalGateway
from erp.modules.finance.application import ChangePayable, PayableCommandMetadata
from erp.modules.finance.domain import (
    Payable,
    PayableApprovalStatus,
    PayableStatus,
    ProvisionalEntryOrigin,
    ProvisionalFinancialEntry,
    SegregationOfDutiesViolation,
)
from erp.modules.finance.infrastructure import (
    FINANCE_APPROVAL_CONSUMER,
    FINANCE_DIVERGENCE_CONSUMER,
    PayableApprovalDecisionConsumer,
    PayableDivergenceConsumer,
    PayableGovernanceRepository,
    PayableRepository,
    PostgresPayableStore,
    ProvisionalEntryRepository,
)
from erp.modules.workflow.domain import ApprovalMode, WorkflowDefinition, WorkflowStepDefinition
from erp.modules.workflow.infrastructure import WorkflowRepository
from erp.modules.workflow.infrastructure.workflow_model import (
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)
from erp.platform.audit import AuditEventModel
from erp.platform.errors import ApplicationError
from erp.platform.inbox import InboxEventModel
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.test_payable_repository import finance_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


@asynccontextmanager
async def governance_fixture() -> AsyncIterator[ProcurementFixture]:
    async with finance_fixture() as data:
        try:
            yield data
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(InboxEventModel).where(
                        InboxEventModel.consumer_name.in_(
                            (FINANCE_APPROVAL_CONSUMER, FINANCE_DIVERGENCE_CONSUMER)
                        )
                    )
                )
                await session.execute(
                    delete(OutboxEventModel).where(
                        OutboxEventModel.payload["company_id"].as_string() == str(data.company_id)
                    )
                )
                await session.execute(
                    delete(AuditEventModel).where(
                        AuditEventModel.company_id == data.company_id,
                        AuditEventModel.module == "finance",
                    )
                )
                await session.execute(
                    delete(ApprovalDecisionModel).where(
                        ApprovalDecisionModel.company_id == data.company_id
                    )
                )
                await session.execute(
                    delete(WorkflowStepInstanceModel).where(
                        WorkflowStepInstanceModel.company_id == data.company_id
                    )
                )
                await session.execute(
                    delete(WorkflowInstanceModel).where(
                        WorkflowInstanceModel.company_id == data.company_id
                    )
                )
                await session.execute(
                    delete(WorkflowStepDefinitionModel).where(
                        WorkflowStepDefinitionModel.company_id == data.company_id
                    )
                )
                await session.execute(
                    delete(WorkflowDefinitionModel).where(
                        WorkflowDefinitionModel.company_id == data.company_id
                    )
                )


def _title(data: ProcurementFixture, *, provisional_entry_id: UUID | None = None) -> Payable:
    return Payable.create(
        company_id=data.company_id,
        number=f"AP-161-{uuid4().hex[:8]}",
        supplier_id=uuid4(),
        supplier_tax_id="12345678000195",
        created_by=data.actor_id,
        provisional_entry_id=provisional_entry_id,
        nominal_amount=Decimal("110.00"),
        installment_plan=((date(2026, 12, 15), Decimal("110.00")),),
    )


async def _approval_policy(data: ProcurementFixture) -> None:
    definition = WorkflowDefinition.create(
        company_id=data.company_id,
        code=f"PAYABLE-{uuid4().hex[:8]}",
        name="Payable authority policy",
        source_module="FINANCE",
        source_type="PAYABLE",
        approval_mode=ApprovalMode.SEQUENTIAL,
    )
    step = WorkflowStepDefinition.create(
        company_id=data.company_id,
        sequence=1,
        code="FINANCE_MANAGER",
        name="Finance manager",
        required_permission="finance.payable.approve",
        threshold_amount=Decimal("100.00"),
    )
    async with data.database.session() as session, session.begin():
        await WorkflowRepository(session, company_id=data.company_id).add_definition(
            definition, steps=(step,), actor_id=data.actor_id
        )


def _command(data: ProcurementFixture, title: Payable) -> ChangePayable:
    return ChangePayable(
        company_id=data.company_id,
        payable_id=title.id,
        expected_version=title.version,
        metadata=PayableCommandMetadata(uuid4(), uuid4()),
    )


def test_high_value_self_submission_opens_m22_and_decision_is_idempotent() -> None:
    async def scenario() -> None:
        async with governance_fixture() as data:
            await _approval_policy(data)
            title = _title(data)
            async with data.database.session() as session, session.begin():
                await PayableRepository(session, company_id=data.company_id).add(
                    title, actor_id=data.actor_id
                )
            changed = await PostgresPayableStore(
                data.database,
                ttl_seconds=3600,
                approval_gateway=M22PayableApprovalGateway(),
            ).submit(
                _command(data, title),
                actor_id=data.actor_id,
                granted_permissions=frozenset({"finance.payable.approve"}),
            )
            assert changed.status is PayableStatus.PENDING_APPROVAL
            async with data.database.session() as session:
                governance = await PayableGovernanceRepository(
                    session, company_id=data.company_id
                ).get(title.id)
                assert governance is not None
                assert governance.approval_status is PayableApprovalStatus.PENDING
                assert governance.workflow_instance_id is not None
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(WorkflowInstanceModel)
                        .where(WorkflowInstanceModel.id == governance.workflow_instance_id)
                    )
                    == 1
                )
                workflow_id = governance.workflow_instance_id
            consumer = PayableApprovalDecisionConsumer(data.database)
            with pytest.raises(SegregationOfDutiesViolation):
                await consumer.consume(_approval_event(data, title.id, workflow_id, data.actor_id))
            approver = uuid4()
            envelope = _approval_event(data, title.id, workflow_id, approver)
            first = await consumer.consume(envelope)
            replay = await consumer.consume(envelope)
            assert first.processed is True
            assert replay.duplicate is True
            async with data.database.session() as session:
                approved = await PayableRepository(session, company_id=data.company_id).get(
                    title.id
                )
                governance = await PayableGovernanceRepository(
                    session, company_id=data.company_id
                ).get(title.id)
                assert approved is not None
                assert approved.status is PayableStatus.APPROVED
                assert approved.decision_by == approver
                assert governance is not None
                assert governance.approval_status is PayableApprovalStatus.APPROVED
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(OutboxEventModel)
                        .where(
                            OutboxEventModel.aggregate_id == title.id,
                            OutboxEventModel.source_module == "finance",
                            OutboxEventModel.payload["message_type"].as_string()
                            == "PayableApproved",
                        )
                    )
                    == 1
                )

    asyncio.run(scenario())


def test_reconciliation_block_prevents_approval_request() -> None:
    async def scenario() -> None:
        async with governance_fixture() as data:
            purchase_order_id = uuid4()
            provision = ProvisionalFinancialEntry.create(
                company_id=data.company_id,
                origin=ProvisionalEntryOrigin.APPROVED_PURCHASE_ORDER,
                source_id=purchase_order_id,
                source_version=1,
                supplier_id=uuid4(),
                supplier_tax_id="12345678000195",
                amount=Decimal("110.00"),
                created_by=data.actor_id,
            )
            title = _title(data, provisional_entry_id=provision.id)
            async with data.database.session() as session, session.begin():
                provisions = ProvisionalEntryRepository(session, company_id=data.company_id)
                await provisions.add(provision, actor_id=data.actor_id)
                await PayableRepository(session, company_id=data.company_id).add(
                    title, actor_id=data.actor_id
                )
                await provisions.save(provision.convert(title.id), actor_id=data.actor_id)
            envelope = _divergence_event(data, purchase_order_id)
            result = await PayableDivergenceConsumer(data.database).consume(envelope)
            assert result.processed is True
            with pytest.raises(ApplicationError) as captured:
                await PostgresPayableStore(data.database, ttl_seconds=3600).submit(
                    _command(data, title),
                    actor_id=data.actor_id,
                    granted_permissions=frozenset(),
                )
            assert captured.value.code == "PAYABLE_DIVERGENCE_BLOCKED"
            async with data.database.session() as session:
                unchanged = await PayableRepository(session, company_id=data.company_id).get(
                    title.id
                )
                assert unchanged is not None
                assert unchanged.status is PayableStatus.DRAFT

    asyncio.run(scenario())


def test_outbox_failure_rolls_back_payable_governance_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        async with governance_fixture() as data:
            title = _title(data)
            async with data.database.session() as session, session.begin():
                await PayableRepository(session, company_id=data.company_id).add(
                    title, actor_id=data.actor_id
                )

            async def fail_enqueue(*args: object, **kwargs: object) -> None:
                raise RuntimeError("forced outbox failure")

            monkeypatch.setattr(OutboxService, "enqueue", fail_enqueue)
            with pytest.raises(RuntimeError, match="forced outbox failure"):
                await PostgresPayableStore(data.database, ttl_seconds=3600).submit(
                    _command(data, title),
                    actor_id=data.actor_id,
                    granted_permissions=frozenset(),
                )
            async with data.database.session() as session:
                unchanged = await PayableRepository(session, company_id=data.company_id).get(
                    title.id
                )
                assert unchanged is not None
                assert unchanged.status is PayableStatus.DRAFT
                assert (
                    await PayableGovernanceRepository(session, company_id=data.company_id).get(
                        title.id
                    )
                    is None
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AuditEventModel)
                        .where(
                            AuditEventModel.company_id == data.company_id,
                            AuditEventModel.entity_id == title.id,
                        )
                    )
                    == 0
                )

    asyncio.run(scenario())


def _approval_event(
    data: ProcurementFixture,
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


def _divergence_event(data: ProcurementFixture, purchase_order_id: UUID) -> MessageEnvelope:
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type="FiscalReceivingReconciled",
        event_version=1,
        producer_module="fiscal",
        producer_domain="fiscal",
        aggregate_type="fiscal_receiving_reconciliation",
        aggregate_id=uuid4(),
        aggregate_version=1,
        company_id=data.company_id,
        branch_id=None,
        correlation_id=uuid4(),
        request_id=uuid4(),
        causation_id=None,
        payload={
            "reconciliation_id": str(uuid4()),
            "purchase_order_id": str(purchase_order_id),
            "financial_blocked": True,
            "physical_pending": True,
        },
    )
