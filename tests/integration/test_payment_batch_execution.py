"""M12 payment-batch execution, M22 approval and atomic Outbox coverage."""

import asyncio
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.apps.api.treasury_execution import M22PaymentBatchApprovalGateway
from erp.modules.finance.application import (
    FINANCE_TREASURY_BATCH_APPROVE,
    PAYMENT_BATCH_APPROVED,
    PAYMENT_BATCH_CREATED,
    PAYMENT_BATCH_RELEASED,
    ApprovePaymentBatch,
    ChangePaymentBatch,
    CreatePaymentBatch,
    PaymentBatchEvent,
    PaymentBatchService,
    TreasuryCommandMetadata,
)
from erp.modules.finance.domain import (
    BankRemittanceFormat,
    MatchingGateStatus,
    PayableInstallmentPaymentSnapshot,
    PayableInstallmentStatus,
    PayableStatus,
    PaymentBatchStatus,
    PaymentExecutionMode,
)
from erp.modules.finance.infrastructure import (
    BatchAuditLogModel,
    PaymentBatchModel,
    PaymentBatchRepository,
    PostgresPaymentBatchEventPublisher,
    RemittanceAdapterRegistry,
)
from erp.modules.workflow.application.decisions import (
    CommandMetadata,
    DecideWorkflowInstance,
)
from erp.modules.workflow.domain import (
    ApprovalDecisionKind,
    ApprovalMode,
    WorkflowDefinition,
    WorkflowStepDefinition,
)
from erp.modules.workflow.infrastructure import (
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowRepository,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
    apply_workflow_decision,
)
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_treasury_repository import TreasuryFixture, treasury_fixture

pytestmark = pytest.mark.integration


class CandidateProvider:
    def __init__(self, value: PayableInstallmentPaymentSnapshot) -> None:
        self._value = value

    async def select(
        self,
        *,
        company_id: UUID,
        installment_ids: tuple[UUID, ...],
    ) -> tuple[PayableInstallmentPaymentSnapshot, ...]:
        if self._value.company_id != company_id:
            return ()
        if self._value.installment_id not in installment_ids:
            return ()
        return (self._value,)


def test_batch_creation_dry_run_m22_approval_and_release_are_atomic() -> None:
    async def scenario() -> None:
        async with treasury_fixture() as fixture:
            data = fixture.matching.data
            candidate = _candidate(fixture)
            metadata = TreasuryCommandMetadata.new()
            async with data.database.session() as session, session.begin():
                await _add_payment_workflow(session, data.company_id, data.actor_id)
                repository = PaymentBatchRepository(session, company_id=data.company_id)
                approvals = M22PaymentBatchApprovalGateway(session)
                service = PaymentBatchService(
                    repository,
                    CandidateProvider(candidate),
                    approvals,
                    RemittanceAdapterRegistry(),
                    PostgresPaymentBatchEventPublisher(session),
                )
                created = await service.create(
                    CreatePaymentBatch(
                        company_id=data.company_id,
                        code=f"EXEC-{uuid4().hex[:10]}",
                        treasury_account_id=uuid4(),
                        scheduled_date=date(2026, 12, 9),
                        remittance_format=BankRemittanceFormat.CNAB_240,
                        execution_mode=PaymentExecutionMode.PRODUCTION,
                        installment_ids=(candidate.installment_id,),
                        metadata=metadata,
                    ),
                    actor_id=fixture.batch_creator,
                )
                assert created.batch.status is PaymentBatchStatus.DRAFT
                assert created.event_id is not None

                dry_run = await service.dry_run(
                    ChangePaymentBatch(
                        data.company_id,
                        created.batch.id,
                        created.batch.version,
                        metadata,
                    )
                )
                assert dry_run.dry_run is True
                assert dry_run.filename.startswith("DRYRUN-")
                assert dry_run.total_amount == Decimal("125.40")
                assert {len(line) for line in dry_run.content.decode("ascii").splitlines()} == {240}

                pending = await service.submit_for_approval(
                    ChangePaymentBatch(
                        data.company_id,
                        created.batch.id,
                        created.batch.version,
                        metadata,
                    ),
                    actor_id=fixture.batch_creator,
                )
                assert pending.batch.status is PaymentBatchStatus.PENDING_APPROVAL
                assert pending.workflow_instance_id is not None

                workflows = WorkflowRepository(session, company_id=data.company_id)
                workflow = await workflows.get_instance(pending.workflow_instance_id)
                assert workflow is not None
                steps = await workflows.list_step_instances(workflow_instance_id=workflow.id)
                decided = await apply_workflow_decision(
                    session,
                    DecideWorkflowInstance(
                        company_id=data.company_id,
                        workflow_instance_id=workflow.id,
                        step_instance_id=steps[0].id,
                        expected_version=workflow.version,
                        decision=ApprovalDecisionKind.APPROVED,
                        reason_code="PAYMENT_BATCH_APPROVED",
                        comment="Approved by treasury authority.",
                        metadata=CommandMetadata(
                            request_id=metadata.request_id,
                            correlation_id=metadata.correlation_id,
                        ),
                    ),
                    actor_id=fixture.batch_approver,
                    actor_permissions=frozenset({str(FINANCE_TREASURY_BATCH_APPROVE)}),
                )
                assert decided.detail.instance.status.value == "APPROVED"

                approved = await service.approve(
                    ApprovePaymentBatch(
                        company_id=data.company_id,
                        payment_batch_id=created.batch.id,
                        expected_version=pending.batch.version,
                        metadata=metadata,
                        workflow_instance_id=workflow.id,
                    )
                )
                assert approved.batch.status is PaymentBatchStatus.APPROVED
                assert approved.batch.approved_by == fixture.batch_approver

                released = await service.release(
                    ChangePaymentBatch(
                        data.company_id,
                        created.batch.id,
                        approved.batch.version,
                        metadata,
                    ),
                    actor_id=fixture.batch_executor,
                )
                assert released.batch.status is PaymentBatchStatus.RELEASED
                assert released.remittance is not None
                assert released.remittance.dry_run is False
                assert released.remittance.filename.startswith("REMESSA-")

                audit = await repository.audit_log(created.batch.id)
                assert [entry.to_status for entry in audit] == [
                    "DRAFT",
                    "PENDING_APPROVAL",
                    "APPROVED",
                    "RELEASED",
                ]
                events = tuple(
                    await session.scalars(
                        select(OutboxEventModel)
                        .where(
                            OutboxEventModel.source_module == "finance",
                            OutboxEventModel.aggregate_id == created.batch.id,
                        )
                        .order_by(OutboxEventModel.occurred_at, OutboxEventModel.event_type)
                    )
                )
                assert {event.event_type for event in events} == {
                    PAYMENT_BATCH_CREATED,
                    PAYMENT_BATCH_APPROVED,
                    PAYMENT_BATCH_RELEASED,
                }
                released_event = next(
                    event for event in events if event.event_type == PAYMENT_BATCH_RELEASED
                )
                assert released_event.payload["payload"]["remittance"]["checksum_sha256"] == (
                    released.remittance.checksum_sha256
                )

                await _cleanup_workflow_and_events(session, data.company_id, created.batch.id)

    asyncio.run(scenario())


def test_outbox_failure_rolls_back_batch_and_append_only_audit() -> None:
    class FailingEvents:
        async def publish(
            self,
            event: PaymentBatchEvent,
            *,
            metadata: TreasuryCommandMetadata,
        ) -> UUID:
            del event, metadata
            raise RuntimeError("outbox unavailable")

    async def scenario() -> None:
        async with treasury_fixture() as fixture:
            data = fixture.matching.data
            candidate = _candidate(fixture)
            created_id: UUID | None = None

            async def fail_transaction() -> None:
                nonlocal created_id
                async with data.database.session() as session, session.begin():
                    service = PaymentBatchService(
                        PaymentBatchRepository(session, company_id=data.company_id),
                        CandidateProvider(candidate),
                        M22PaymentBatchApprovalGateway(session),
                        RemittanceAdapterRegistry(),
                        FailingEvents(),
                    )
                    result = await service.create(
                        CreatePaymentBatch(
                            company_id=data.company_id,
                            code=f"ROLLBACK-{uuid4().hex[:8]}",
                            treasury_account_id=uuid4(),
                            scheduled_date=date(2026, 12, 9),
                            remittance_format=BankRemittanceFormat.CNAB_400,
                            execution_mode=PaymentExecutionMode.HOMOLOGATION,
                            installment_ids=(candidate.installment_id,),
                        ),
                        actor_id=fixture.batch_creator,
                    )
                    created_id = result.batch.id

            with pytest.raises(RuntimeError, match="outbox unavailable"):
                await fail_transaction()

            async with data.database.session() as session:
                batch_count = await session.scalar(
                    select(func.count())
                    .select_from(PaymentBatchModel)
                    .where(PaymentBatchModel.company_id == data.company_id)
                )
                audit_count = await session.scalar(
                    select(func.count())
                    .select_from(BatchAuditLogModel)
                    .where(BatchAuditLogModel.company_id == data.company_id)
                )
                assert created_id is None
                assert batch_count == 0
                assert audit_count == 0

    asyncio.run(scenario())


def _candidate(fixture: TreasuryFixture) -> PayableInstallmentPaymentSnapshot:
    batch_item = fixture.batch.items[0]
    return PayableInstallmentPaymentSnapshot(
        company_id=batch_item.company_id,
        payable_id=batch_item.payable_id,
        installment_id=batch_item.installment_id,
        supplier_id=batch_item.supplier_id,
        amount=batch_item.amount,
        currency=batch_item.currency,
        due_date=batch_item.due_date,
        payable_status=PayableStatus.APPROVED,
        installment_status=PayableInstallmentStatus.OPEN,
        matching_status=MatchingGateStatus.MATCHED,
        matching_session_id=batch_item.matching_session_id,
        payable_created_by=batch_item.payable_created_by,
        payable_approved_by=batch_item.payable_approved_by,
        beneficiary=batch_item.beneficiary,
    )


async def _add_payment_workflow(session: AsyncSession, company_id: UUID, actor_id: UUID) -> None:
    definition = WorkflowDefinition.create(
        company_id=company_id,
        code=f"TREASURY-{uuid4().hex[:8]}",
        name="Treasury payment approval",
        source_module="FINANCE",
        source_type="PAYMENT_BATCH",
        approval_mode=ApprovalMode.SEQUENTIAL,
    )
    step = WorkflowStepDefinition.create(
        company_id=company_id,
        sequence=1,
        code="TREASURY_APPROVAL",
        name="Treasury authority",
        required_permission=str(FINANCE_TREASURY_BATCH_APPROVE),
        threshold_amount=None,
    )
    await WorkflowRepository(session, company_id=company_id).add_definition(
        definition,
        steps=(step,),
        actor_id=actor_id,
    )


async def _cleanup_workflow_and_events(
    session: AsyncSession,
    company_id: UUID,
    batch_id: UUID,
) -> None:
    await session.execute(delete(OutboxEventModel).where(OutboxEventModel.aggregate_id == batch_id))
    instance_ids = tuple(
        await session.scalars(
            select(WorkflowInstanceModel.id).where(
                WorkflowInstanceModel.company_id == company_id,
                WorkflowInstanceModel.source_module == "FINANCE",
                WorkflowInstanceModel.source_type == "PAYMENT_BATCH",
                WorkflowInstanceModel.source_id == batch_id,
            )
        )
    )
    if instance_ids:
        await session.execute(
            delete(OutboxEventModel).where(OutboxEventModel.aggregate_id.in_(instance_ids))
        )
        await session.execute(
            delete(ApprovalDecisionModel).where(
                ApprovalDecisionModel.workflow_instance_id.in_(instance_ids)
            )
        )
        await session.execute(
            delete(WorkflowStepInstanceModel).where(
                WorkflowStepInstanceModel.workflow_instance_id.in_(instance_ids)
            )
        )
        await session.execute(
            delete(WorkflowInstanceModel).where(WorkflowInstanceModel.id.in_(instance_ids))
        )
    definitions = tuple(
        await session.scalars(
            select(WorkflowDefinitionModel.id).where(
                WorkflowDefinitionModel.company_id == company_id,
                WorkflowDefinitionModel.source_module == "FINANCE",
                WorkflowDefinitionModel.source_type == "PAYMENT_BATCH",
            )
        )
    )
    if definitions:
        await session.execute(
            delete(WorkflowStepDefinitionModel).where(
                WorkflowStepDefinitionModel.definition_id.in_(definitions)
            )
        )
        await session.execute(
            delete(WorkflowDefinitionModel).where(WorkflowDefinitionModel.id.in_(definitions))
        )
