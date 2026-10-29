"""Candidate adapter backed by accepted receivable and Treasury events."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import BankCandidateSource, BankMatchCandidate
from erp.modules.finance.domain import (
    BankMovement,
    BankMovementDirection,
    FinancialReconciliationCandidate,
    InvalidBankStatementError,
)
from erp.modules.finance.infrastructure.bank_reconciliation_event_model import (
    BankReconciliationCandidateModel,
)


class EventBankCandidateProvider:
    """Expose active upstream projections through the pure matching contract."""

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
        lower = movement.booked_on - timedelta(days=self._search_window_days)
        upper = movement.booked_on + timedelta(days=self._search_window_days)
        rows = await self._session.scalars(
            select(BankReconciliationCandidateModel)
            .where(
                BankReconciliationCandidateModel.company_id == self._company_id,
                BankReconciliationCandidateModel.active.is_(True),
                BankReconciliationCandidateModel.direction == movement.direction.value,
                BankReconciliationCandidateModel.expected_on >= lower,
                BankReconciliationCandidateModel.expected_on <= upper,
            )
            .order_by(
                BankReconciliationCandidateModel.expected_on,
                BankReconciliationCandidateModel.id,
            )
        )
        return tuple(_candidate(value) for value in rows)


def _candidate(model: BankReconciliationCandidateModel) -> BankMatchCandidate:
    return BankMatchCandidate(
        FinancialReconciliationCandidate(
            reference_id=model.id,
            company_id=model.company_id,
            expected_on=model.expected_on,
            amount=model.amount,
            direction=BankMovementDirection(model.direction),
            document_number=model.document_number,
        ),
        BankCandidateSource(model.source),
    )


__all__ = ["EventBankCandidateProvider"]
