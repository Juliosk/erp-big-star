"""Tenant-bound persistence adapter for M12 payment batches."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.domain import (
    BankAccountType,
    BankPaymentConfirmation,
    BankPaymentFailure,
    BankPaymentFailureKind,
    BankRemittanceFormat,
    BeneficiaryBankAccount,
    InvalidTreasuryRuleError,
    PaymentBatch,
    PaymentBatchItem,
    PaymentBatchStatus,
    PaymentExecutionMode,
    TreasuryConflictError,
    TreasuryScopeError,
    TreasuryVersionConflictError,
)
from erp.modules.finance.infrastructure.treasury_model import (
    BatchAuditLogModel,
    PaymentBatchItemModel,
    PaymentBatchModel,
)


class PaymentBatchRepository:
    """Persist payment batches without owning commit or rollback boundaries."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, batch: PaymentBatch, *, actor_id: UUID) -> None:
        self._write_scope(batch, actor_id)
        if batch.version != 1 or batch.status is not PaymentBatchStatus.DRAFT:
            raise ValueError("A new payment batch must start draft at version one.")
        self._session.add(_batch_model(batch, actor_id))
        await self._flush()
        self._session.add_all(_item_models(batch, actor_id))
        self._session.add(
            _audit_model(
                batch,
                actor_id=actor_id,
                from_status=None,
                occurred_at=datetime.now(UTC),
            )
        )
        await self._flush()

    async def get(self, batch_id: UUID) -> PaymentBatch | None:
        root = await self._session.scalar(
            select(PaymentBatchModel)
            .where(
                PaymentBatchModel.company_id == self._company_id,
                PaymentBatchModel.id == batch_id,
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return _batch(root, await self._items(root.id))

    async def get_for_update(self, batch_id: UUID) -> PaymentBatch | None:
        root = await self._session.scalar(
            select(PaymentBatchModel)
            .where(
                PaymentBatchModel.company_id == self._company_id,
                PaymentBatchModel.id == batch_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return _batch(root, await self._items(root.id))

    async def list(
        self,
        *,
        status: PaymentBatchStatus | None = None,
        scheduled_from: date | None = None,
        scheduled_to: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PaymentBatch, ...]:
        _page(limit, offset)
        statement = select(PaymentBatchModel).where(
            PaymentBatchModel.company_id == self._company_id
        )
        if status is not None:
            if not isinstance(status, PaymentBatchStatus):
                raise ValueError("status must be an official payment-batch status.")
            statement = statement.where(PaymentBatchModel.status == status.value)
        if scheduled_from is not None:
            statement = statement.where(PaymentBatchModel.scheduled_date >= scheduled_from)
        if scheduled_to is not None:
            statement = statement.where(PaymentBatchModel.scheduled_date <= scheduled_to)
        roots = await self._session.scalars(
            statement.order_by(PaymentBatchModel.scheduled_date, PaymentBatchModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        values = []
        for root in roots:
            values.append(_batch(root, await self._items(root.id)))
        return tuple(values)

    async def save(
        self,
        batch: PaymentBatch,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> PaymentBatch:
        self._write_scope(batch, actor_id)
        compare = batch.version - 1 if expected_version is None else expected_version
        if compare < 1 or batch.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        current = await self.get(batch.id)
        if current is None or current.version != compare:
            raise TreasuryVersionConflictError(
                f"Payment batch expected version {compare} is stale."
            )
        _validate_frozen_state(current, batch)
        _validate_transition(current.status, batch.status)
        updated = cast(
            CursorResult[Any],
            await self._session.execute(
                update(PaymentBatchModel)
                .where(
                    PaymentBatchModel.company_id == self._company_id,
                    PaymentBatchModel.id == batch.id,
                    PaymentBatchModel.version == compare,
                )
                .values(**_batch_values(batch, actor_id))
            ),
        )
        if updated.rowcount != 1:
            raise TreasuryVersionConflictError(
                f"Payment batch expected version {compare} is stale."
            )
        self._session.add(
            _audit_model(
                batch,
                actor_id=actor_id,
                from_status=current.status,
                occurred_at=_transition_occurred_at(batch),
            )
        )
        await self._flush()
        return batch

    async def audit_log(self, batch_id: UUID) -> tuple[BatchAuditLogModel, ...]:
        values = await self._session.scalars(
            select(BatchAuditLogModel)
            .where(
                BatchAuditLogModel.company_id == self._company_id,
                BatchAuditLogModel.payment_batch_id == batch_id,
            )
            .order_by(BatchAuditLogModel.aggregate_version)
        )
        return tuple(values)

    async def _items(self, batch_id: UUID) -> tuple[PaymentBatchItemModel, ...]:
        values = await self._session.scalars(
            select(PaymentBatchItemModel)
            .where(
                PaymentBatchItemModel.company_id == self._company_id,
                PaymentBatchItemModel.payment_batch_id == batch_id,
            )
            .order_by(PaymentBatchItemModel.due_date, PaymentBatchItemModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(values)

    def _write_scope(self, batch: PaymentBatch, actor_id: UUID) -> None:
        if not isinstance(batch, PaymentBatch):
            raise TypeError("batch must be a PaymentBatch.")
        if batch.company_id != self._company_id:
            raise TreasuryScopeError("Payment batch is outside the selected company.")
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise ValueError("An explicit non-zero actor UUID is required.")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise TreasuryConflictError(
                    "Payment-batch code, item or audit version already exists for this company."
                ) from error
            raise


def _batch_model(batch: PaymentBatch, actor_id: UUID) -> PaymentBatchModel:
    return PaymentBatchModel(
        id=batch.id,
        company_id=batch.company_id,
        created_by=batch.created_by,
        **_batch_values(batch, actor_id),
    )


def _batch_values(batch: PaymentBatch, actor_id: UUID) -> dict[str, Any]:
    confirmation = batch.bank_confirmation
    failure = batch.bank_failure
    return {
        "code": batch.code,
        "treasury_account_id": batch.treasury_account_id,
        "scheduled_date": batch.scheduled_date,
        "currency": batch.currency,
        "total_amount": batch.total_amount,
        "remittance_format": batch.remittance_format.value,
        "execution_mode": batch.execution_mode.value,
        "status": batch.status.value,
        "approved_by": batch.approved_by,
        "released_by": batch.released_by,
        "submission_protocol": batch.submission_protocol,
        "submitted_at": batch.submitted_at,
        "transition_reason": batch.transition_reason,
        "bank_confirmation_protocol": confirmation.protocol if confirmation else None,
        "bank_confirmation_status": confirmation.status_code if confirmation else None,
        "bank_confirmed_at": confirmation.confirmed_at if confirmation else None,
        "bank_confirmed_amount": confirmation.confirmed_amount if confirmation else None,
        "bank_failure_kind": failure.kind.value if failure else None,
        "bank_failure_protocol": failure.protocol if failure else None,
        "bank_failure_status": failure.status_code if failure else None,
        "bank_failed_at": failure.failed_at if failure else None,
        "bank_failure_reason": failure.reason if failure else None,
        "version": batch.version,
        "updated_at": datetime.now(UTC),
        "updated_by": actor_id,
    }


def _item_models(batch: PaymentBatch, actor_id: UUID) -> list[PaymentBatchItemModel]:
    return [
        PaymentBatchItemModel(
            id=item.id,
            company_id=item.company_id,
            payment_batch_id=item.batch_id,
            payable_id=item.payable_id,
            installment_id=item.installment_id,
            supplier_id=item.supplier_id,
            amount=item.amount,
            currency=item.currency,
            due_date=item.due_date,
            matching_session_id=item.matching_session_id,
            payable_created_by=item.payable_created_by,
            payable_approved_by=item.payable_approved_by,
            beneficiary_bank_code=item.beneficiary.bank_code,
            beneficiary_branch_number=item.beneficiary.branch_number,
            beneficiary_account_number=item.beneficiary.account_number,
            beneficiary_account_digit=item.beneficiary.account_digit,
            beneficiary_account_type=item.beneficiary.account_type.value,
            beneficiary_holder_name=item.beneficiary.holder_name,
            beneficiary_holder_tax_id=item.beneficiary.holder_tax_id,
            created_by=actor_id,
        )
        for item in batch.items
    ]


def _audit_model(
    batch: PaymentBatch,
    *,
    actor_id: UUID,
    from_status: PaymentBatchStatus | None,
    occurred_at: datetime,
) -> BatchAuditLogModel:
    return BatchAuditLogModel(
        id=uuid4(),
        company_id=batch.company_id,
        payment_batch_id=batch.id,
        from_status=from_status.value if from_status is not None else None,
        to_status=batch.status.value,
        aggregate_version=batch.version,
        actor_id=actor_id,
        occurred_at=occurred_at,
        details={
            "code": batch.code,
            "currency": batch.currency,
            "total_amount": str(batch.total_amount),
            "item_count": len(batch.items),
            "execution_mode": batch.execution_mode.value,
            "remittance_format": batch.remittance_format.value,
            "transition_reason": batch.transition_reason,
            "submission_protocol": batch.submission_protocol,
            "bank_confirmation_protocol": (
                batch.bank_confirmation.protocol if batch.bank_confirmation else None
            ),
            "bank_failure_protocol": batch.bank_failure.protocol if batch.bank_failure else None,
            "bank_failure_status": (batch.bank_failure.status_code if batch.bank_failure else None),
            "bank_failure_kind": batch.bank_failure.kind.value if batch.bank_failure else None,
        },
    )


def _batch(
    root: PaymentBatchModel,
    items: tuple[PaymentBatchItemModel, ...],
) -> PaymentBatch:
    return PaymentBatch(
        id=root.id,
        company_id=root.company_id,
        code=root.code,
        treasury_account_id=root.treasury_account_id,
        scheduled_date=root.scheduled_date,
        created_by=root.created_by,
        remittance_format=BankRemittanceFormat(root.remittance_format),
        execution_mode=PaymentExecutionMode(root.execution_mode),
        items=tuple(_item(item) for item in items),
        status=PaymentBatchStatus(root.status),
        version=root.version,
        approved_by=root.approved_by,
        released_by=root.released_by,
        submission_protocol=root.submission_protocol,
        submitted_at=root.submitted_at,
        transition_reason=root.transition_reason,
        bank_confirmation=_confirmation(root),
        bank_failure=_failure(root),
    )


def _item(model: PaymentBatchItemModel) -> PaymentBatchItem:
    return PaymentBatchItem(
        id=model.id,
        company_id=model.company_id,
        batch_id=model.payment_batch_id,
        payable_id=model.payable_id,
        installment_id=model.installment_id,
        supplier_id=model.supplier_id,
        amount=model.amount,
        currency=model.currency,
        due_date=model.due_date,
        matching_session_id=model.matching_session_id,
        payable_created_by=model.payable_created_by,
        payable_approved_by=model.payable_approved_by,
        beneficiary=BeneficiaryBankAccount(
            bank_code=model.beneficiary_bank_code,
            branch_number=model.beneficiary_branch_number,
            account_number=model.beneficiary_account_number,
            account_digit=model.beneficiary_account_digit,
            account_type=BankAccountType(model.beneficiary_account_type),
            holder_name=model.beneficiary_holder_name,
            holder_tax_id=model.beneficiary_holder_tax_id,
        ),
    )


def _confirmation(root: PaymentBatchModel) -> BankPaymentConfirmation | None:
    values = (
        root.bank_confirmation_protocol,
        root.bank_confirmation_status,
        root.bank_confirmed_at,
        root.bank_confirmed_amount,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise InvalidTreasuryRuleError("Persisted bank confirmation is incomplete.")
    return BankPaymentConfirmation(
        protocol=cast(str, root.bank_confirmation_protocol),
        status_code=cast(str, root.bank_confirmation_status),
        confirmed_at=cast(datetime, root.bank_confirmed_at),
        confirmed_amount=cast(Decimal, root.bank_confirmed_amount),
    )


def _failure(root: PaymentBatchModel) -> BankPaymentFailure | None:
    values = (
        root.bank_failure_kind,
        root.bank_failure_protocol,
        root.bank_failure_status,
        root.bank_failed_at,
        root.bank_failure_reason,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise InvalidTreasuryRuleError("Persisted bank failure evidence is incomplete.")
    return BankPaymentFailure(
        kind=BankPaymentFailureKind(cast(str, root.bank_failure_kind)),
        protocol=cast(str, root.bank_failure_protocol),
        status_code=cast(str, root.bank_failure_status),
        failed_at=cast(datetime, root.bank_failed_at),
        reason=cast(str, root.bank_failure_reason),
    )


def _validate_frozen_state(current: PaymentBatch, candidate: PaymentBatch) -> None:
    if (
        current.company_id != candidate.company_id
        or current.code != candidate.code
        or current.treasury_account_id != candidate.treasury_account_id
        or current.scheduled_date != candidate.scheduled_date
        or current.created_by != candidate.created_by
        or current.remittance_format != candidate.remittance_format
        or current.execution_mode != candidate.execution_mode
        or current.items != candidate.items
    ):
        raise InvalidTreasuryRuleError(
            "Payment-batch identity, execution policy and item snapshots are immutable."
        )


def _validate_transition(current: PaymentBatchStatus, candidate: PaymentBatchStatus) -> None:
    allowed = {
        PaymentBatchStatus.DRAFT: {
            PaymentBatchStatus.PENDING_APPROVAL,
            PaymentBatchStatus.CANCELLED,
        },
        PaymentBatchStatus.PENDING_APPROVAL: {
            PaymentBatchStatus.APPROVED,
            PaymentBatchStatus.REJECTED,
            PaymentBatchStatus.CANCELLED,
        },
        PaymentBatchStatus.APPROVED: {
            PaymentBatchStatus.RELEASED,
            PaymentBatchStatus.CANCELLED,
        },
        PaymentBatchStatus.RELEASED: {
            PaymentBatchStatus.SUBMITTED,
            PaymentBatchStatus.CANCELLED,
        },
        PaymentBatchStatus.SUBMITTED: {
            PaymentBatchStatus.CONFIRMED,
            PaymentBatchStatus.FAILED,
        },
    }
    if candidate not in allowed.get(current, set()):
        raise InvalidTreasuryRuleError(
            f"Persistence transition {current.value} -> {candidate.value} is not allowed."
        )


def _transition_occurred_at(batch: PaymentBatch) -> datetime:
    if batch.bank_confirmation is not None:
        return batch.bank_confirmation.confirmed_at
    if batch.bank_failure is not None:
        return batch.bank_failure.failed_at
    return batch.submitted_at or datetime.now(UTC)


def _page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer.")


__all__ = ["PaymentBatchRepository"]
