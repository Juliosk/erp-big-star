"""Framework-neutral orchestration for M12 treasury payment batches."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from erp.modules.finance.domain import (
    BankRemittanceFormat,
    PayableInstallmentPaymentSnapshot,
    PaymentBatch,
    PaymentBatchItem,
    PaymentEligibilityPolicy,
    PaymentExecutionMode,
    TreasurySegregationPolicy,
    TreasuryVersionConflictError,
)
from erp.platform.errors import ApplicationError, ErrorDetail

PAYMENT_BATCH_CREATED = "PaymentBatchCreated"
PAYMENT_BATCH_APPROVED = "PaymentBatchApproved"
PAYMENT_BATCH_RELEASED = "PaymentBatchReleased"


@dataclass(frozen=True, slots=True)
class TreasuryCommandMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None

    @classmethod
    def new(cls) -> TreasuryCommandMetadata:
        return cls(uuid4(), uuid4())


@dataclass(frozen=True, slots=True)
class CreatePaymentBatch:
    company_id: UUID
    code: str
    treasury_account_id: UUID
    scheduled_date: date
    remittance_format: BankRemittanceFormat
    execution_mode: PaymentExecutionMode
    installment_ids: tuple[UUID, ...]
    metadata: TreasuryCommandMetadata = field(default_factory=TreasuryCommandMetadata.new)


@dataclass(frozen=True, slots=True)
class ChangePaymentBatch:
    company_id: UUID
    payment_batch_id: UUID
    expected_version: int
    metadata: TreasuryCommandMetadata = field(default_factory=TreasuryCommandMetadata.new)


@dataclass(frozen=True, slots=True)
class ApprovePaymentBatch(ChangePaymentBatch):
    workflow_instance_id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class TreasuryApprovalDecision:
    workflow_instance_id: UUID
    decided_by: UUID
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class RemittanceArtifact:
    filename: str
    media_type: str
    content: bytes
    checksum_sha256: str
    record_count: int
    total_amount: Decimal
    dry_run: bool


@dataclass(frozen=True, slots=True)
class PaymentBatchEvent:
    event_type: str
    aggregate: PaymentBatch
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class PaymentBatchMutationResult:
    batch: PaymentBatch
    event_id: UUID | None = None
    workflow_instance_id: UUID | None = None
    remittance: RemittanceArtifact | None = None


class PaymentBatchStore(Protocol):
    async def add(self, batch: PaymentBatch, *, actor_id: UUID) -> None: ...

    async def get(self, batch_id: UUID) -> PaymentBatch | None: ...

    async def save(
        self,
        batch: PaymentBatch,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> PaymentBatch: ...


class PaymentCandidateProvider(Protocol):
    async def select(
        self,
        *,
        company_id: UUID,
        installment_ids: tuple[UUID, ...],
    ) -> tuple[PayableInstallmentPaymentSnapshot, ...]: ...


class PaymentBatchApprovalGateway(Protocol):
    async def request(self, batch: PaymentBatch, *, actor_id: UUID) -> UUID: ...

    async def approved_decision(
        self,
        *,
        company_id: UUID,
        payment_batch_id: UUID,
        workflow_instance_id: UUID,
    ) -> TreasuryApprovalDecision: ...


class RemittanceGeneratorPort(Protocol):
    def generate(self, batch: PaymentBatch, *, dry_run: bool) -> RemittanceArtifact: ...


class PaymentBatchEventPublisher(Protocol):
    async def publish(
        self,
        event: PaymentBatchEvent,
        *,
        metadata: TreasuryCommandMetadata,
    ) -> UUID: ...


class PaymentBatchService:
    """Coordinate eligibility, M22 approval, remittance and atomic effects."""

    def __init__(
        self,
        repository: PaymentBatchStore,
        candidates: PaymentCandidateProvider,
        approvals: PaymentBatchApprovalGateway,
        remittance: RemittanceGeneratorPort,
        events: PaymentBatchEventPublisher,
        *,
        eligibility: PaymentEligibilityPolicy | None = None,
        segregation: TreasurySegregationPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._candidates = candidates
        self._approvals = approvals
        self._remittance = remittance
        self._events = events
        self._eligibility = eligibility or PaymentEligibilityPolicy()
        self._segregation = segregation or TreasurySegregationPolicy()

    async def create(
        self,
        command: CreatePaymentBatch,
        *,
        actor_id: UUID,
    ) -> PaymentBatchMutationResult:
        _validate_create(command, actor_id)
        snapshots = await self._candidates.select(
            company_id=command.company_id,
            installment_ids=command.installment_ids,
        )
        ordered = _ordered_candidates(command, snapshots)
        batch_id = uuid4()
        items = tuple(
            PaymentBatchItem.from_snapshot(
                item_id=uuid4(),
                batch_id=batch_id,
                snapshot=snapshot,
                policy=self._eligibility,
            )
            for snapshot in ordered
        )
        batch = PaymentBatch(
            id=batch_id,
            company_id=command.company_id,
            code=command.code,
            treasury_account_id=command.treasury_account_id,
            scheduled_date=command.scheduled_date,
            created_by=actor_id,
            remittance_format=command.remittance_format,
            execution_mode=command.execution_mode,
            items=items,
        )
        await self._repository.add(batch, actor_id=actor_id)
        event_id = await self._events.publish(
            payment_batch_event(PAYMENT_BATCH_CREATED, batch),
            metadata=command.metadata,
        )
        return PaymentBatchMutationResult(batch, event_id=event_id)

    async def dry_run(
        self,
        command: ChangePaymentBatch,
    ) -> RemittanceArtifact:
        batch = await self._load(command)
        return self._remittance.generate(batch, dry_run=True)

    async def submit_for_approval(
        self,
        command: ChangePaymentBatch,
        *,
        actor_id: UUID,
    ) -> PaymentBatchMutationResult:
        _validate_change(command, actor_id)
        current = await self._load(command)
        pending = current.submit_for_approval()
        workflow_id = await self._approvals.request(pending, actor_id=actor_id)
        saved = await self._save(pending, actor_id=actor_id, expected=current.version)
        return PaymentBatchMutationResult(saved, workflow_instance_id=workflow_id)

    async def approve(
        self,
        command: ApprovePaymentBatch,
    ) -> PaymentBatchMutationResult:
        _validate_change(command, command.workflow_instance_id)
        current = await self._load(command)
        decision = await self._approvals.approved_decision(
            company_id=command.company_id,
            payment_batch_id=current.id,
            workflow_instance_id=command.workflow_instance_id,
        )
        approved = current.approve(
            actor_id=decision.decided_by,
            policy=self._segregation,
        )
        saved = await self._save(
            approved,
            actor_id=decision.decided_by,
            expected=current.version,
        )
        event_id = await self._events.publish(
            payment_batch_event(
                PAYMENT_BATCH_APPROVED,
                saved,
                workflow_instance_id=decision.workflow_instance_id,
                decided_at=decision.decided_at,
            ),
            metadata=command.metadata,
        )
        return PaymentBatchMutationResult(
            saved,
            event_id=event_id,
            workflow_instance_id=decision.workflow_instance_id,
        )

    async def release(
        self,
        command: ChangePaymentBatch,
        *,
        actor_id: UUID,
    ) -> PaymentBatchMutationResult:
        _validate_change(command, actor_id)
        current = await self._load(command)
        released = current.release(actor_id=actor_id, policy=self._segregation)
        artifact = self._remittance.generate(
            released,
            dry_run=released.execution_mode is PaymentExecutionMode.DRY_RUN,
        )
        saved = await self._save(released, actor_id=actor_id, expected=current.version)
        event_id = await self._events.publish(
            payment_batch_event(PAYMENT_BATCH_RELEASED, saved, remittance=artifact),
            metadata=command.metadata,
        )
        return PaymentBatchMutationResult(saved, event_id=event_id, remittance=artifact)

    async def _load(self, command: ChangePaymentBatch) -> PaymentBatch:
        _validate_change(command, None)
        value = await self._repository.get(command.payment_batch_id)
        if value is None or value.company_id != command.company_id:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Payment batch not found.",
                status_code=404,
            )
        if value.version != command.expected_version:
            raise _version_conflict(command.expected_version)
        return value

    async def _save(
        self,
        batch: PaymentBatch,
        *,
        actor_id: UUID,
        expected: int,
    ) -> PaymentBatch:
        try:
            return await self._repository.save(
                batch,
                actor_id=actor_id,
                expected_version=expected,
            )
        except TreasuryVersionConflictError as error:
            raise _version_conflict(expected) from error


def payment_batch_event(
    event_type: str,
    batch: PaymentBatch,
    *,
    workflow_instance_id: UUID | None = None,
    decided_at: datetime | None = None,
    remittance: RemittanceArtifact | None = None,
) -> PaymentBatchEvent:
    payload: dict[str, object] = {
        "company_id": str(batch.company_id),
        "payment_batch_id": str(batch.id),
        "code": batch.code,
        "status": batch.status.value,
        "aggregate_version": batch.version,
        "currency": batch.currency,
        "total_amount": str(batch.total_amount),
        "item_count": len(batch.items),
        "scheduled_date": batch.scheduled_date.isoformat(),
        "remittance_format": batch.remittance_format.value,
        "execution_mode": batch.execution_mode.value,
    }
    if workflow_instance_id is not None:
        payload["workflow_instance_id"] = str(workflow_instance_id)
    if decided_at is not None:
        payload["approved_at"] = decided_at.isoformat()
    if remittance is not None:
        payload["remittance"] = {
            "filename": remittance.filename,
            "checksum_sha256": remittance.checksum_sha256,
            "record_count": remittance.record_count,
            "dry_run": remittance.dry_run,
        }
    if batch.bank_confirmation is not None:
        payload["bank_confirmation"] = {
            "protocol": batch.bank_confirmation.protocol,
            "status_code": batch.bank_confirmation.status_code,
            "confirmed_at": batch.bank_confirmation.confirmed_at.isoformat(),
            "confirmed_amount": str(batch.bank_confirmation.confirmed_amount),
        }
    if batch.bank_failure is not None:
        payload["bank_failure"] = {
            "kind": batch.bank_failure.kind.value,
            "protocol": batch.bank_failure.protocol,
            "status_code": batch.bank_failure.status_code,
            "failed_at": batch.bank_failure.failed_at.isoformat(),
            "reason": batch.bank_failure.reason,
        }
    return PaymentBatchEvent(event_type, batch, payload)


def _ordered_candidates(
    command: CreatePaymentBatch,
    candidates: tuple[PayableInstallmentPaymentSnapshot, ...],
) -> tuple[PayableInstallmentPaymentSnapshot, ...]:
    indexed: dict[UUID, PayableInstallmentPaymentSnapshot] = {}
    for candidate in candidates:
        if candidate.company_id != command.company_id:
            continue
        if candidate.installment_id in indexed:
            raise ApplicationError(
                code="TREASURY_CANDIDATE_CONFLICT",
                message="Payment candidate selection returned duplicate installments.",
                status_code=409,
            )
        indexed[candidate.installment_id] = candidate
    if set(indexed) != set(command.installment_ids):
        raise ApplicationError(
            code="PAYMENT_INSTALLMENT_NOT_ELIGIBLE",
            message="One or more requested installments are unavailable in this company.",
            status_code=422,
        )
    return tuple(indexed[value] for value in command.installment_ids)


def _validate_create(command: CreatePaymentBatch, actor_id: UUID) -> None:
    if not isinstance(command, CreatePaymentBatch):
        raise TypeError("command must be a CreatePaymentBatch.")
    _uuid(command.company_id, "company_id")
    _uuid(command.treasury_account_id, "treasury_account_id")
    _uuid(actor_id, "actor_id")
    if not command.installment_ids or len(set(command.installment_ids)) != len(
        command.installment_ids
    ):
        raise ValueError("installment_ids must be non-empty and unique.")
    for value in command.installment_ids:
        _uuid(value, "installment_id")


def _validate_change(command: ChangePaymentBatch, actor_id: UUID | None) -> None:
    if not isinstance(command, ChangePaymentBatch):
        raise TypeError("command must be a ChangePaymentBatch.")
    _uuid(command.company_id, "company_id")
    _uuid(command.payment_batch_id, "payment_batch_id")
    if type(command.expected_version) is not int or command.expected_version < 1:
        raise ValueError("expected_version must be a positive integer.")
    if actor_id is not None:
        _uuid(actor_id, "actor_id")


def _uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{field_name} must be a non-zero UUID.")


def _version_conflict(expected_version: int) -> ApplicationError:
    return ApplicationError(
        code="VERSION_CONFLICT",
        message="The payment batch was changed by another transaction.",
        status_code=409,
        details=[ErrorDetail(message=f"Expected version {expected_version} is stale.")],
    )


__all__ = [name for name in globals() if not name.startswith("_")]
