"""Tenant-bound persistence adapter for the M12 Payable aggregate."""

from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.domain import (
    FinanceScopeError,
    FinanceVersionConflictError,
    Payable,
    PayableConflictError,
    PayableInstallment,
    PayableInstallmentStatus,
    PayableStatus,
)
from erp.modules.finance.infrastructure.payable_model import (
    PayableInstallmentModel,
    PayableModel,
)


class PayableRepository:
    """Persist payables without owning commit or rollback boundaries."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, payable: Payable, *, actor_id: UUID) -> None:
        self._write_scope(payable, actor_id)
        if payable.version != 1 or payable.status is not PayableStatus.DRAFT:
            raise ValueError("A new payable must start draft at version one.")
        self._session.add(_payable_model(payable, actor_id))
        await self._flush()
        self._session.add_all(_installment_models(payable, actor_id))
        await self._flush()

    async def get(self, payable_id: UUID) -> Payable | None:
        root = await self._session.scalar(
            select(PayableModel)
            .where(
                PayableModel.company_id == self._company_id,
                PayableModel.id == payable_id,
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return _payable(root, await self._installments(payable_id))

    async def list(
        self,
        *,
        status: PayableStatus | None = None,
        supplier_id: UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        due_from: date | None = None,
        due_to: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Payable, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100.")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer.")
        statement = select(PayableModel).where(PayableModel.company_id == self._company_id)
        if status is not None:
            if not isinstance(status, PayableStatus):
                raise ValueError("status must be an official payable status.")
            statement = statement.where(PayableModel.status == status.value)
        if supplier_id is not None:
            if not isinstance(supplier_id, UUID):
                raise ValueError("supplier_id must be a UUID.")
            statement = statement.where(PayableModel.supplier_id == supplier_id)
        if created_from is not None:
            statement = statement.where(PayableModel.created_at >= created_from)
        if created_to is not None:
            statement = statement.where(PayableModel.created_at <= created_to)
        if due_from is not None or due_to is not None:
            due_statement = select(PayableInstallmentModel.payable_id).where(
                PayableInstallmentModel.company_id == self._company_id
            )
            if due_from is not None:
                due_statement = due_statement.where(PayableInstallmentModel.due_date >= due_from)
            if due_to is not None:
                due_statement = due_statement.where(PayableInstallmentModel.due_date <= due_to)
            statement = statement.where(PayableModel.id.in_(due_statement))
        roots = await self._session.scalars(
            statement.order_by(PayableModel.document_number, PayableModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        values = []
        for root in roots:
            values.append(_payable(root, await self._installments(root.id)))
        return tuple(values)

    async def save(
        self,
        payable: Payable,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> Payable:
        self._write_scope(payable, actor_id)
        compare = payable.version - 1 if expected_version is None else expected_version
        if compare < 1 or payable.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        updated = cast(
            CursorResult[Any],
            await self._session.execute(
                update(PayableModel)
                .where(
                    PayableModel.company_id == self._company_id,
                    PayableModel.id == payable.id,
                    PayableModel.version == compare,
                    PayableModel.document_number == payable.number,
                    PayableModel.supplier_id == payable.supplier_id,
                )
                .values(**_payable_values(payable, actor_id)),
            ),
        )
        if updated.rowcount != 1:
            raise FinanceVersionConflictError(f"Payable expected version {compare} is stale.")
        await self._session.execute(
            delete(PayableInstallmentModel).where(
                PayableInstallmentModel.company_id == self._company_id,
                PayableInstallmentModel.payable_id == payable.id,
            )
        )
        self._session.add_all(_installment_models(payable, actor_id))
        await self._flush()
        return payable

    async def _installments(self, payable_id: UUID) -> tuple[PayableInstallmentModel, ...]:
        values = await self._session.scalars(
            select(PayableInstallmentModel)
            .where(
                PayableInstallmentModel.company_id == self._company_id,
                PayableInstallmentModel.payable_id == payable_id,
            )
            .order_by(PayableInstallmentModel.installment_number)
            .execution_options(populate_existing=True)
        )
        return tuple(values)

    def _write_scope(self, payable: Payable, actor_id: UUID) -> None:
        if payable.company_id != self._company_id:
            raise FinanceScopeError("Payable is outside the selected company.")
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            self._translate(error)

    @staticmethod
    def _translate(error: IntegrityError) -> None:
        if getattr(error.orig, "sqlstate", None) == "23505":
            raise PayableConflictError(
                "Payable document number already exists for this supplier and company."
            ) from error
        raise error


def _payable_model(payable: Payable, actor_id: UUID) -> PayableModel:
    return PayableModel(
        id=payable.id,
        company_id=payable.company_id,
        created_by=payable.created_by,
        **_payable_values(payable, actor_id),
    )


def _payable_values(payable: Payable, actor_id: UUID) -> dict[str, Any]:
    return {
        "document_number": payable.number,
        "supplier_id": payable.supplier_id,
        "supplier_tax_id": payable.supplier_tax_id,
        "provisional_entry_id": payable.provisional_entry_id,
        "currency": payable.currency,
        "nominal_amount": payable.nominal_amount,
        "interest_amount": payable.interest_amount,
        "discount_amount": payable.discount_amount,
        "surcharge_amount": payable.surcharge_amount,
        "status": payable.status.value,
        "decision_by": payable.decision_by,
        "decision_reason": payable.decision_reason,
        "version": payable.version,
        "updated_at": datetime.now(UTC),
        "updated_by": actor_id,
    }


def _installment_models(payable: Payable, actor_id: UUID) -> list[PayableInstallmentModel]:
    return [
        PayableInstallmentModel(
            id=item.id,
            company_id=item.company_id,
            payable_id=item.payable_id,
            installment_number=item.number,
            due_date=item.due_date,
            amount=item.amount,
            status=item.status.value,
            schedule_id=item.schedule_id,
            paid_on=item.paid_on,
            payment_reference=item.payment_reference,
            created_by=actor_id,
            updated_by=actor_id,
        )
        for item in payable.installments
    ]


def _payable(
    root: PayableModel,
    installments: tuple[PayableInstallmentModel, ...],
) -> Payable:
    return Payable(
        id=root.id,
        company_id=root.company_id,
        number=root.document_number,
        supplier_id=root.supplier_id,
        supplier_tax_id=root.supplier_tax_id,
        provisional_entry_id=root.provisional_entry_id,
        currency=root.currency,
        nominal_amount=root.nominal_amount,
        interest_amount=root.interest_amount,
        discount_amount=root.discount_amount,
        surcharge_amount=root.surcharge_amount,
        status=PayableStatus(root.status),
        installments=tuple(_installment(value) for value in installments),
        created_by=root.created_by,
        decision_by=root.decision_by,
        decision_reason=root.decision_reason,
        version=root.version,
    )


def _installment(model: PayableInstallmentModel) -> PayableInstallment:
    return PayableInstallment(
        id=model.id,
        company_id=model.company_id,
        payable_id=model.payable_id,
        number=model.installment_number,
        due_date=model.due_date,
        amount=model.amount,
        status=PayableInstallmentStatus(model.status),
        schedule_id=model.schedule_id,
        paid_on=model.paid_on,
        payment_reference=model.payment_reference,
    )


__all__ = ["PayableRepository"]
