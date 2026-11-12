"""Tenant-bound persistence adapter for M12 payment requests."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.domain import (
    BankAccountType,
    BeneficiaryBankAccount,
    InvalidPaymentRequestError,
    PaymentRequest,
    PaymentRequestItem,
    PaymentRequestStatus,
    TreasuryConflictError,
    TreasuryScopeError,
    TreasuryVersionConflictError,
)
from erp.modules.finance.infrastructure.payment_request_model import (
    PaymentRequestItemModel,
    PaymentRequestModel,
)


class PaymentRequestRepository:
    """Persist payment requests without owning commit or rollback boundaries."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, request: PaymentRequest, *, actor_id: UUID) -> None:
        self._write_scope(request, actor_id)
        if request.version != 1 or request.status is not PaymentRequestStatus.DRAFT:
            raise ValueError("A new payment request must start draft at version one.")
        now = datetime.now(UTC)
        root = PaymentRequestModel(
            id=request.id,
            company_id=request.company_id,
            code=request.code,
            treasury_account_id=request.treasury_account_id,
            requested_by=request.requested_by,
            requested_at=request.requested_at,
            scheduled_on=request.scheduled_on,
            purpose=request.purpose,
            created_at=now,
            **_root_values(request, actor_id=actor_id, occurred_at=now),
        )
        self._session.add(root)
        # No ORM relationship is needed to persist the immutable item snapshots.
        # Flush the root explicitly so the composite tenant FK is enforced in a
        # deterministic order, while the caller still owns commit and rollback.
        await self._flush()
        self._session.add_all(
            _item_model(request, item, sequence=sequence, actor_id=actor_id)
            for sequence, item in enumerate(request.items, start=1)
        )
        await self._flush()

    async def get(self, request_id: UUID) -> PaymentRequest | None:
        root = await self._session.scalar(
            select(PaymentRequestModel)
            .where(
                PaymentRequestModel.company_id == self._company_id,
                PaymentRequestModel.id == request_id,
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return _request(root, await self._items(root.id))

    async def get_for_update(self, request_id: UUID) -> PaymentRequest | None:
        root = await self._session.scalar(
            select(PaymentRequestModel)
            .where(
                PaymentRequestModel.company_id == self._company_id,
                PaymentRequestModel.id == request_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return _request(root, await self._items(root.id))

    async def list(
        self,
        *,
        status: PaymentRequestStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PaymentRequest, ...]:
        _page(limit, offset)
        statement = select(PaymentRequestModel).where(
            PaymentRequestModel.company_id == self._company_id
        )
        if status is not None:
            if not isinstance(status, PaymentRequestStatus):
                raise ValueError("status must be an official payment-request status.")
            statement = statement.where(PaymentRequestModel.status == status.value)
        roots = await self._session.scalars(
            statement.order_by(
                PaymentRequestModel.scheduled_on,
                PaymentRequestModel.code,
                PaymentRequestModel.id,
            )
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        values = []
        for root in roots:
            values.append(_request(root, await self._items(root.id)))
        return tuple(values)

    async def save(
        self,
        request: PaymentRequest,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> PaymentRequest:
        self._write_scope(request, actor_id)
        compare = request.version - 1 if expected_version is None else expected_version
        if compare < 1 or request.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        current = await self.get(request.id)
        if current is None or current.version != compare:
            raise TreasuryVersionConflictError(
                f"Payment request expected version {compare} is stale."
            )
        _validate_frozen_state(current, request)
        _validate_transition(current.status, request.status)
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(PaymentRequestModel)
                .where(
                    PaymentRequestModel.company_id == self._company_id,
                    PaymentRequestModel.id == request.id,
                    PaymentRequestModel.version == compare,
                )
                .values(
                    **_root_values(
                        request,
                        actor_id=actor_id,
                        occurred_at=datetime.now(UTC),
                    )
                )
            ),
        )
        if result.rowcount != 1:
            raise TreasuryVersionConflictError(
                f"Payment request expected version {compare} is stale."
            )
        await self._flush()
        return request

    async def _items(self, request_id: UUID) -> tuple[PaymentRequestItemModel, ...]:
        values = await self._session.scalars(
            select(PaymentRequestItemModel)
            .where(
                PaymentRequestItemModel.company_id == self._company_id,
                PaymentRequestItemModel.payment_request_id == request_id,
            )
            .order_by(PaymentRequestItemModel.item_sequence)
            .execution_options(populate_existing=True)
        )
        return tuple(values)

    def _write_scope(self, request: PaymentRequest, actor_id: UUID) -> None:
        if not isinstance(request, PaymentRequest):
            raise TypeError("request must be a PaymentRequest.")
        if request.company_id != self._company_id:
            raise TreasuryScopeError("Payment request is outside the selected company.")
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise ValueError("An explicit non-zero actor UUID is required.")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise TreasuryConflictError(
                    "Payment-request code or installment already exists for this company."
                ) from error
            raise


def _root_values(
    request: PaymentRequest,
    *,
    actor_id: UUID,
    occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "currency": request.currency,
        "total_amount": request.total_amount,
        "status": request.status.value,
        "workflow_instance_id": request.workflow_instance_id,
        "approved_by": request.approved_by,
        "approved_at": request.approved_at,
        "batch_id": request.batch_id,
        "transition_reason": request.transition_reason,
        "version": request.version,
        "updated_at": occurred_at,
        "updated_by": actor_id,
    }


def _item_model(
    request: PaymentRequest,
    item: PaymentRequestItem,
    *,
    sequence: int,
    actor_id: UUID,
) -> PaymentRequestItemModel:
    return PaymentRequestItemModel(
        id=item.id,
        company_id=item.company_id,
        payment_request_id=request.id,
        item_sequence=sequence,
        payable_id=item.payable_id,
        installment_id=item.installment_id,
        supplier_id=item.supplier_id,
        matching_session_id=item.matching_session_id,
        amount=item.amount,
        currency=item.currency,
        due_date=item.due_date,
        beneficiary_bank_code=item.beneficiary.bank_code,
        beneficiary_branch_number=item.beneficiary.branch_number,
        beneficiary_account_number=item.beneficiary.account_number,
        beneficiary_account_digit=item.beneficiary.account_digit,
        beneficiary_account_type=item.beneficiary.account_type.value,
        beneficiary_holder_name=item.beneficiary.holder_name,
        beneficiary_holder_tax_id=item.beneficiary.holder_tax_id,
        created_by=actor_id,
    )


def _request(
    root: PaymentRequestModel,
    items: tuple[PaymentRequestItemModel, ...],
) -> PaymentRequest:
    return PaymentRequest(
        id=root.id,
        company_id=root.company_id,
        code=root.code,
        treasury_account_id=root.treasury_account_id,
        requested_by=root.requested_by,
        requested_at=root.requested_at,
        scheduled_on=root.scheduled_on,
        purpose=root.purpose,
        items=tuple(_item(item) for item in items),
        status=PaymentRequestStatus(root.status),
        version=root.version,
        workflow_instance_id=root.workflow_instance_id,
        approved_by=root.approved_by,
        approved_at=root.approved_at,
        batch_id=root.batch_id,
        transition_reason=root.transition_reason,
    )


def _item(model: PaymentRequestItemModel) -> PaymentRequestItem:
    return PaymentRequestItem(
        id=model.id,
        company_id=model.company_id,
        payable_id=model.payable_id,
        installment_id=model.installment_id,
        supplier_id=model.supplier_id,
        matching_session_id=model.matching_session_id,
        amount=model.amount,
        currency=model.currency,
        due_date=model.due_date,
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


def _validate_frozen_state(current: PaymentRequest, candidate: PaymentRequest) -> None:
    if (
        current.company_id != candidate.company_id
        or current.code != candidate.code
        or current.treasury_account_id != candidate.treasury_account_id
        or current.requested_by != candidate.requested_by
        or current.requested_at != candidate.requested_at
        or current.scheduled_on != candidate.scheduled_on
        or current.purpose != candidate.purpose
        or current.items != candidate.items
    ):
        raise InvalidPaymentRequestError(
            "Payment-request identity, schedule, purpose and item snapshots are immutable."
        )


def _validate_transition(
    current: PaymentRequestStatus,
    candidate: PaymentRequestStatus,
) -> None:
    allowed = {
        PaymentRequestStatus.DRAFT: {
            PaymentRequestStatus.PENDING_APPROVAL,
            PaymentRequestStatus.CANCELLED,
        },
        PaymentRequestStatus.PENDING_APPROVAL: {
            PaymentRequestStatus.APPROVED,
            PaymentRequestStatus.REJECTED,
            PaymentRequestStatus.CANCELLED,
        },
        PaymentRequestStatus.APPROVED: {
            PaymentRequestStatus.BATCHED,
            PaymentRequestStatus.CANCELLED,
        },
    }
    if candidate not in allowed.get(current, set()):
        raise InvalidPaymentRequestError(
            f"Persistence transition {current.value} -> {candidate.value} is not allowed."
        )


def _page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer.")


__all__ = ["PaymentRequestRepository"]
