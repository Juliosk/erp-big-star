"""Framework-free orchestration tests for M12 payment batches."""

from collections.abc import Coroutine
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from erp.modules.finance.application import (
    PAYMENT_BATCH_APPROVED,
    PAYMENT_BATCH_CREATED,
    PAYMENT_BATCH_RELEASED,
    ApprovePaymentBatch,
    ChangePaymentBatch,
    CreatePaymentBatch,
    PaymentBatchEvent,
    PaymentBatchService,
    TreasuryApprovalDecision,
    TreasuryCommandMetadata,
)
from erp.modules.finance.domain import (
    BankAccountType,
    BankRemittanceFormat,
    BeneficiaryBankAccount,
    MatchingGateStatus,
    PayableInstallmentPaymentSnapshot,
    PayableInstallmentStatus,
    PayableStatus,
    PaymentBatch,
    PaymentBatchStatus,
    PaymentExecutionMode,
)
from erp.modules.finance.infrastructure import RemittanceAdapterRegistry


class MemoryRepository:
    def __init__(self) -> None:
        self.value: PaymentBatch | None = None

    async def add(self, batch: PaymentBatch, *, actor_id: UUID) -> None:
        del actor_id
        self.value = batch

    async def get(self, batch_id: UUID) -> PaymentBatch | None:
        if self.value is not None and self.value.id == batch_id:
            return self.value
        return None

    async def save(
        self,
        batch: PaymentBatch,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> PaymentBatch:
        del actor_id
        assert self.value is not None
        assert self.value.version == expected_version
        self.value = batch
        return batch


class Candidates:
    def __init__(self, candidate: PayableInstallmentPaymentSnapshot) -> None:
        self.candidate = candidate

    async def select(
        self,
        *,
        company_id: UUID,
        installment_ids: tuple[UUID, ...],
    ) -> tuple[PayableInstallmentPaymentSnapshot, ...]:
        assert company_id == self.candidate.company_id
        assert installment_ids == (self.candidate.installment_id,)
        return (self.candidate,)


class Approvals:
    def __init__(self, approver_id: UUID) -> None:
        self.workflow_id = uuid4()
        self.approver_id = approver_id

    async def request(self, batch: PaymentBatch, *, actor_id: UUID) -> UUID:
        assert batch.status is PaymentBatchStatus.PENDING_APPROVAL
        assert actor_id == batch.created_by
        return self.workflow_id

    async def approved_decision(
        self,
        *,
        company_id: UUID,
        payment_batch_id: UUID,
        workflow_instance_id: UUID,
    ) -> TreasuryApprovalDecision:
        del company_id, payment_batch_id
        assert workflow_instance_id == self.workflow_id
        return TreasuryApprovalDecision(
            workflow_instance_id,
            self.approver_id,
            datetime(2026, 12, 8, 10, 0, tzinfo=UTC),
        )


class Events:
    def __init__(self) -> None:
        self.values: list[PaymentBatchEvent] = []

    async def publish(
        self,
        event: PaymentBatchEvent,
        *,
        metadata: TreasuryCommandMetadata,
    ) -> UUID:
        assert metadata.request_id.int != 0
        self.values.append(event)
        return uuid4()


def test_service_orchestrates_candidate_dry_run_approval_release_and_events() -> None:
    async def scenario() -> None:
        candidate = _candidate()
        repository = MemoryRepository()
        approvals = Approvals(uuid4())
        events = Events()
        service = PaymentBatchService(
            repository,
            Candidates(candidate),
            approvals,
            RemittanceAdapterRegistry(),
            events,
        )
        creator = uuid4()
        executor = uuid4()
        metadata = TreasuryCommandMetadata.new()

        created = await service.create(
            CreatePaymentBatch(
                company_id=candidate.company_id,
                code="PAY-174",
                treasury_account_id=uuid4(),
                scheduled_date=date(2026, 12, 9),
                remittance_format=BankRemittanceFormat.CNAB_240,
                execution_mode=PaymentExecutionMode.PRODUCTION,
                installment_ids=(candidate.installment_id,),
                metadata=metadata,
            ),
            actor_id=creator,
        )
        simulated = await service.dry_run(
            ChangePaymentBatch(
                candidate.company_id,
                created.batch.id,
                created.batch.version,
                metadata,
            )
        )
        pending = await service.submit_for_approval(
            ChangePaymentBatch(
                candidate.company_id,
                created.batch.id,
                created.batch.version,
                metadata,
            ),
            actor_id=creator,
        )
        approved = await service.approve(
            ApprovePaymentBatch(
                company_id=candidate.company_id,
                payment_batch_id=created.batch.id,
                expected_version=pending.batch.version,
                metadata=metadata,
                workflow_instance_id=approvals.workflow_id,
            )
        )
        released = await service.release(
            ChangePaymentBatch(
                candidate.company_id,
                created.batch.id,
                approved.batch.version,
                metadata,
            ),
            actor_id=executor,
        )

        assert simulated.dry_run is True
        assert pending.workflow_instance_id == approvals.workflow_id
        assert approved.batch.approved_by == approvals.approver_id
        assert released.batch.status is PaymentBatchStatus.RELEASED
        assert released.remittance is not None
        assert released.remittance.dry_run is False
        assert [value.event_type for value in events.values] == [
            PAYMENT_BATCH_CREATED,
            PAYMENT_BATCH_APPROVED,
            PAYMENT_BATCH_RELEASED,
        ]

    _run_immediate(scenario())


def _candidate() -> PayableInstallmentPaymentSnapshot:
    return PayableInstallmentPaymentSnapshot(
        company_id=uuid4(),
        payable_id=uuid4(),
        installment_id=uuid4(),
        supplier_id=uuid4(),
        amount=Decimal("125.40"),
        currency="BRL",
        due_date=date(2026, 12, 10),
        payable_status=PayableStatus.APPROVED,
        installment_status=PayableInstallmentStatus.OPEN,
        matching_status=MatchingGateStatus.MATCHED,
        matching_session_id=uuid4(),
        payable_created_by=uuid4(),
        payable_approved_by=uuid4(),
        beneficiary=BeneficiaryBankAccount(
            bank_code="001",
            branch_number="1234",
            account_number="987654",
            account_digit="X",
            account_type=BankAccountType.CHECKING,
            holder_name="Fornecedor Treasury",
            holder_tax_id="12345678000195",
        ),
    )


def _run_immediate[ResultT](coroutine: Coroutine[Any, Any, ResultT]) -> ResultT:
    """Drive an I/O-free coroutine and fail if a unit fake suspends externally."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return cast(ResultT, completed.value)
    raise AssertionError("The treasury unit scenario unexpectedly awaited external I/O.")
