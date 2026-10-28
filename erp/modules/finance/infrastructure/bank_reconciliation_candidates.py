"""PostgreSQL candidate adapters for automatic bank reconciliation."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application.bank_reconciliation import (
    BankCandidateSource,
    BankMatchCandidate,
)
from erp.modules.finance.domain import (
    BankMovement,
    BankMovementDirection,
    FinancialReconciliationCandidate,
    InvalidBankStatementError,
)
from erp.modules.finance.infrastructure.payable_model import (
    PayableInstallmentModel,
    PayableModel,
)


class PayableBankCandidateProvider:
    """Expose settled M12 payable installments through the pure matching contract."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        company_id: UUID,
        search_window_days: int = 31,
    ) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        if type(search_window_days) is not int or not 0 <= search_window_days <= 90:
            raise ValueError("search_window_days must be an integer between 0 and 90.")
        self._session = session
        self._company_id = company_id
        self._search_window_days = search_window_days

    async def candidates_for(self, movement: BankMovement) -> tuple[BankMatchCandidate, ...]:
        if not isinstance(movement, BankMovement):
            raise TypeError("movement must be a BankMovement.")
        if movement.company_id != self._company_id:
            raise InvalidBankStatementError("Movement is outside the candidate-provider company.")
        if movement.direction is not BankMovementDirection.DEBIT:
            return ()
        lower = movement.booked_on - timedelta(days=self._search_window_days)
        upper = movement.booked_on + timedelta(days=self._search_window_days)
        rows = await self._session.execute(
            select(PayableInstallmentModel, PayableModel.document_number)
            .join(
                PayableModel,
                and_(
                    PayableModel.company_id == PayableInstallmentModel.company_id,
                    PayableModel.id == PayableInstallmentModel.payable_id,
                ),
            )
            .where(
                PayableInstallmentModel.company_id == self._company_id,
                PayableInstallmentModel.status == "PAID",
                PayableInstallmentModel.paid_on.is_not(None),
                PayableInstallmentModel.paid_on >= lower,
                PayableInstallmentModel.paid_on <= upper,
                PayableModel.status == "PAID",
            )
            .order_by(PayableInstallmentModel.paid_on, PayableInstallmentModel.id)
        )
        values = []
        for installment, document_number in rows.all():
            if installment.paid_on is None:
                raise InvalidBankStatementError(
                    "Persisted paid installment has no settlement date."
                )
            values.append(
                BankMatchCandidate(
                    FinancialReconciliationCandidate(
                        reference_id=installment.id,
                        company_id=installment.company_id,
                        expected_on=installment.paid_on,
                        amount=installment.amount,
                        direction=BankMovementDirection.DEBIT,
                        document_number=(
                            installment.payment_reference or document_number
                        ),
                    ),
                    BankCandidateSource.PAYABLE_M12,
                )
            )
        return tuple(values)


__all__ = ["PayableBankCandidateProvider"]
