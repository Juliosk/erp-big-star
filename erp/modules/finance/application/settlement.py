"""Framework-neutral bank settlement orchestration for M12 Treasury."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from erp.modules.finance.application.treasury import (
    PaymentBatchEventPublisher,
    TreasuryCommandMetadata,
    payment_batch_event,
)
from erp.modules.finance.domain import (
    BankPaymentConfirmation,
    BankPaymentFailure,
    BankPaymentFailureKind,
    BankRemittanceFormat,
    Payable,
    PaymentBatch,
    PaymentBatchStatus,
    TreasuryVersionConflictError,
)
from erp.platform.errors import ApplicationError, ErrorDetail

PAYMENT_BATCH_SUBMITTED = "PaymentBatchSubmitted"
PAYMENT_BATCH_CONFIRMED = "PaymentBatchConfirmed"
PAYMENT_BATCH_FAILED = "PaymentBatchFailed"


class BankReturnOutcome(StrEnum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SubmitPaymentBatch:
    company_id: UUID
    payment_batch_id: UUID
    expected_version: int
    protocol: str
    occurred_at: datetime
    metadata: TreasuryCommandMetadata = field(default_factory=TreasuryCommandMetadata.new)


@dataclass(frozen=True, slots=True)
class BankSettlementNotification:
    company_id: UUID
    payment_batch_id: UUID
    protocol: str
    status_code: str
    outcome: BankReturnOutcome
    occurred_at: datetime
    amount: Decimal | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class BankReturnDocument:
    remittance_format: BankRemittanceFormat
    records: tuple[BankSettlementNotification, ...]
    source_reference: str


@dataclass(frozen=True, slots=True)
class PaymentSettlementResult:
    batch: PaymentBatch
    payables: tuple[Payable, ...]
    event_id: UUID | None
    replayed: bool = False


class PaymentBatchSettlementRepository(Protocol):
    async def get_for_update(self, batch_id: UUID) -> PaymentBatch | None: ...

    async def save(
        self,
        batch: PaymentBatch,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> PaymentBatch: ...


class PayableSettlementRepository(Protocol):
    async def get_for_update(self, payable_id: UUID) -> Payable | None: ...

    async def save(
        self,
        payable: Payable,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> Payable: ...


class BankReturnParserPort(Protocol):
    def parse(self, content: bytes, *, company_id: UUID) -> BankReturnDocument: ...


class PaymentSettlementService:
    """Schedule, settle or release payables from immutable bank evidence."""

    def __init__(
        self,
        batches: PaymentBatchSettlementRepository,
        payables: PayableSettlementRepository,
        events: PaymentBatchEventPublisher,
    ) -> None:
        self._batches = batches
        self._payables = payables
        self._events = events

    async def record_submission(
        self,
        command: SubmitPaymentBatch,
        *,
        actor_id: UUID,
    ) -> PaymentSettlementResult:
        _validate_submission(command, actor_id)
        current = await self._batch(command.company_id, command.payment_batch_id)
        _expected_version(current, command.expected_version)
        scheduled = await self._change_payables(
            current,
            actor_id=actor_id,
            operation="SCHEDULE",
        )
        submitted = current.mark_submitted(
            protocol=command.protocol,
            occurred_at=command.occurred_at,
        )
        saved = await self._save_batch(
            submitted,
            actor_id=actor_id,
            expected=current.version,
        )
        event_id = await self._events.publish(
            payment_batch_event(PAYMENT_BATCH_SUBMITTED, saved),
            metadata=command.metadata,
        )
        return PaymentSettlementResult(saved, scheduled, event_id)

    async def process(
        self,
        notification: BankSettlementNotification,
        *,
        actor_id: UUID,
        metadata: TreasuryCommandMetadata,
    ) -> PaymentSettlementResult:
        _validate_notification(notification, actor_id)
        current = await self._batch(
            notification.company_id,
            notification.payment_batch_id,
        )
        replay = await self._replay(current, notification)
        if replay is not None:
            return replay
        if current.status is not PaymentBatchStatus.SUBMITTED:
            raise ApplicationError(
                code="PAYMENT_BATCH_NOT_SUBMITTED",
                message="Only a submitted payment batch can process a bank return.",
                status_code=409,
            )
        if notification.outcome is BankReturnOutcome.CONFIRMED:
            return await self._confirm(current, notification, actor_id, metadata)
        return await self._fail(current, notification, actor_id, metadata)

    async def _confirm(
        self,
        current: PaymentBatch,
        notification: BankSettlementNotification,
        actor_id: UUID,
        metadata: TreasuryCommandMetadata,
    ) -> PaymentSettlementResult:
        if notification.amount != current.total_amount:
            raise ApplicationError(
                code="BANK_SETTLEMENT_AMOUNT_MISMATCH",
                message="The bank confirmation amount does not reconcile with the batch.",
                status_code=422,
            )
        changed = await self._change_payables(
            current,
            actor_id=actor_id,
            operation="SETTLE",
            occurred_at=notification.occurred_at,
            reference=notification.protocol,
        )
        confirmed = current.confirm(
            BankPaymentConfirmation(
                protocol=notification.protocol,
                status_code=notification.status_code,
                confirmed_at=notification.occurred_at,
                confirmed_amount=current.total_amount,
            )
        )
        saved = await self._save_batch(
            confirmed,
            actor_id=actor_id,
            expected=current.version,
        )
        event_id = await self._events.publish(
            payment_batch_event(PAYMENT_BATCH_CONFIRMED, saved),
            metadata=metadata,
        )
        return PaymentSettlementResult(saved, changed, event_id)

    async def _fail(
        self,
        current: PaymentBatch,
        notification: BankSettlementNotification,
        actor_id: UUID,
        metadata: TreasuryCommandMetadata,
    ) -> PaymentSettlementResult:
        assert notification.reason is not None
        changed = await self._change_payables(
            current,
            actor_id=actor_id,
            operation="RELEASE",
        )
        failed = current.fail(
            BankPaymentFailure(
                kind=BankPaymentFailureKind(notification.outcome.value),
                protocol=notification.protocol,
                status_code=notification.status_code,
                failed_at=notification.occurred_at,
                reason=notification.reason,
            )
        )
        saved = await self._save_batch(
            failed,
            actor_id=actor_id,
            expected=current.version,
        )
        event_id = await self._events.publish(
            payment_batch_event(PAYMENT_BATCH_FAILED, saved),
            metadata=metadata,
        )
        return PaymentSettlementResult(saved, changed, event_id)

    async def _change_payables(
        self,
        batch: PaymentBatch,
        *,
        actor_id: UUID,
        operation: str,
        occurred_at: datetime | None = None,
        reference: str | None = None,
    ) -> tuple[Payable, ...]:
        grouped: dict[UUID, tuple[UUID, ...]] = {}
        for item in batch.items:
            grouped[item.payable_id] = (*grouped.get(item.payable_id, ()), item.installment_id)
        changed: list[Payable] = []
        for payable_id, installment_ids in grouped.items():
            payable = await self._payables.get_for_update(payable_id)
            if payable is None or payable.company_id != batch.company_id:
                raise _not_found("Payable")
            numbers = _installment_numbers(payable, installment_ids)
            if operation == "SCHEDULE":
                updated = payable.schedule_installments_for_payment(
                    installment_numbers=numbers,
                    schedule_id=batch.id,
                )
            elif operation == "SETTLE":
                assert occurred_at is not None
                assert reference is not None
                updated = payable.settle_installments(
                    installment_numbers=numbers,
                    schedule_id=batch.id,
                    paid_on=occurred_at.date(),
                    payment_reference=reference,
                )
            else:
                updated = payable.release_payment_schedule(
                    installment_numbers=numbers,
                    schedule_id=batch.id,
                )
            changed.append(
                await self._payables.save(
                    updated,
                    actor_id=actor_id,
                    expected_version=payable.version,
                )
            )
        return tuple(changed)

    async def _batch(self, company_id: UUID, batch_id: UUID) -> PaymentBatch:
        value = await self._batches.get_for_update(batch_id)
        if value is None or value.company_id != company_id:
            raise _not_found("Payment batch")
        return value

    async def _save_batch(
        self,
        batch: PaymentBatch,
        *,
        actor_id: UUID,
        expected: int,
    ) -> PaymentBatch:
        try:
            return await self._batches.save(
                batch,
                actor_id=actor_id,
                expected_version=expected,
            )
        except TreasuryVersionConflictError as error:
            raise ApplicationError(
                code="VERSION_CONFLICT",
                message="The payment batch was changed by another transaction.",
                status_code=409,
                details=[ErrorDetail(message=f"Expected version {expected} is stale.")],
            ) from error

    async def _replay(
        self,
        current: PaymentBatch,
        notification: BankSettlementNotification,
    ) -> PaymentSettlementResult | None:
        if (
            current.status is PaymentBatchStatus.CONFIRMED
            and notification.outcome is BankReturnOutcome.CONFIRMED
            and current.bank_confirmation is not None
            and current.bank_confirmation.protocol == notification.protocol
        ):
            return PaymentSettlementResult(
                current,
                await self._load_payables(current),
                None,
                replayed=True,
            )
        if (
            current.status is PaymentBatchStatus.FAILED
            and notification.outcome in {BankReturnOutcome.REJECTED, BankReturnOutcome.FAILED}
            and current.bank_failure is not None
            and current.bank_failure.protocol == notification.protocol
            and current.bank_failure.kind.value == notification.outcome.value
        ):
            return PaymentSettlementResult(
                current,
                await self._load_payables(current),
                None,
                replayed=True,
            )
        return None

    async def _load_payables(self, batch: PaymentBatch) -> tuple[Payable, ...]:
        values: list[Payable] = []
        for payable_id in dict.fromkeys(item.payable_id for item in batch.items):
            payable = await self._payables.get_for_update(payable_id)
            if payable is None or payable.company_id != batch.company_id:
                raise _not_found("Payable")
            values.append(payable)
        return tuple(values)


def _installment_numbers(payable: Payable, installment_ids: tuple[UUID, ...]) -> tuple[int, ...]:
    selected = tuple(item.number for item in payable.installments if item.id in installment_ids)
    if len(selected) != len(installment_ids):
        raise ApplicationError(
            code="PAYMENT_INSTALLMENT_NOT_FOUND",
            message="A payment-batch installment does not belong to its payable.",
            status_code=409,
        )
    return selected


def _validate_submission(command: SubmitPaymentBatch, actor_id: UUID) -> None:
    if not isinstance(command, SubmitPaymentBatch):
        raise TypeError("command must be a SubmitPaymentBatch.")
    _uuid(command.company_id, "company_id")
    _uuid(command.payment_batch_id, "payment_batch_id")
    _uuid(actor_id, "actor_id")
    if type(command.expected_version) is not int or command.expected_version < 1:
        raise ValueError("expected_version must be a positive integer.")
    _aware(command.occurred_at, "occurred_at")


def _validate_notification(notification: BankSettlementNotification, actor_id: UUID) -> None:
    if not isinstance(notification, BankSettlementNotification):
        raise TypeError("notification must be a BankSettlementNotification.")
    _uuid(notification.company_id, "company_id")
    _uuid(notification.payment_batch_id, "payment_batch_id")
    _uuid(actor_id, "actor_id")
    if not notification.protocol.strip() or len(notification.protocol.strip()) > 120:
        raise ValueError("protocol must contain between 1 and 120 characters.")
    if not notification.status_code.strip() or len(notification.status_code.strip()) > 40:
        raise ValueError("status_code must contain between 1 and 40 characters.")
    if not isinstance(notification.outcome, BankReturnOutcome):
        raise ValueError("outcome must be a BankReturnOutcome.")
    _aware(notification.occurred_at, "occurred_at")
    if notification.outcome is BankReturnOutcome.CONFIRMED:
        if notification.amount is None:
            raise ValueError("confirmed bank returns require amount.")
    elif notification.reason is None or not notification.reason.strip():
        raise ValueError("failed bank returns require reason.")


def _expected_version(batch: PaymentBatch, expected: int) -> None:
    if batch.version != expected:
        raise ApplicationError(
            code="VERSION_CONFLICT",
            message="The payment batch was changed by another transaction.",
            status_code=409,
        )


def _uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{field_name} must be a non-zero UUID.")


def _aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND",
        message=f"{resource} not found.",
        status_code=404,
    )


__all__ = [name for name in globals() if not name.startswith("_")]
