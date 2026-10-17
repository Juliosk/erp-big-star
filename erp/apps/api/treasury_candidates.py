"""Cross-context composition of M12 payment candidates and M6 matching facts."""

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import CreateTreasuryBatch
from erp.modules.finance.domain import (
    MatchingGateStatus,
    PayableInstallmentPaymentSnapshot,
    PayableInstallmentStatus,
    PayableStatus,
    PaymentBatchStatus,
)
from erp.modules.finance.infrastructure import (
    PayableGovernanceModel,
    PayableInstallmentModel,
    PayableModel,
    PaymentBatchItemModel,
    PaymentBatchModel,
)
from erp.modules.procurement.infrastructure import MatchingSessionModel
from erp.platform.errors import ApplicationError

_ACTIVE_BATCH_STATUSES = (
    PaymentBatchStatus.DRAFT.value,
    PaymentBatchStatus.PENDING_APPROVAL.value,
    PaymentBatchStatus.APPROVED.value,
    PaymentBatchStatus.RELEASED.value,
    PaymentBatchStatus.SUBMITTED.value,
)


class PostgresTreasuryPaymentCandidateProvider:
    """Translate M12 payable and M6 matching records into the pure eligibility port."""

    def __init__(self, session: AsyncSession, command: CreateTreasuryBatch) -> None:
        self._session = session
        self._beneficiaries = {
            item.installment_id: item.beneficiary for item in command.installments
        }

    async def select(
        self,
        *,
        company_id: UUID,
        installment_ids: tuple[UUID, ...],
    ) -> tuple[PayableInstallmentPaymentSnapshot, ...]:
        rows = tuple(
            await self._session.execute(
                select(PayableInstallmentModel, PayableModel)
                .join(
                    PayableModel,
                    (PayableModel.company_id == PayableInstallmentModel.company_id)
                    & (PayableModel.id == PayableInstallmentModel.payable_id),
                )
                .where(
                    PayableInstallmentModel.company_id == company_id,
                    PayableInstallmentModel.id.in_(installment_ids),
                )
            )
        )
        indexed = {installment.id: (installment, payable) for installment, payable in rows}
        values = []
        for installment_id in installment_ids:
            pair = indexed.get(installment_id)
            beneficiary = self._beneficiaries.get(installment_id)
            if pair is None or beneficiary is None:
                continue
            installment, payable = pair
            matching = await self._matching(company_id, payable.id)
            if matching is None or payable.decision_by is None:
                continue
            governance = await self._session.get(
                PayableGovernanceModel,
                (company_id, payable.id),
            )
            if beneficiary.holder_tax_id != payable.supplier_tax_id:
                raise ApplicationError(
                    code="VALIDATION_ERROR",
                    message="Beneficiary tax id must match the payable supplier tax id.",
                    status_code=422,
                )
            values.append(
                PayableInstallmentPaymentSnapshot(
                    company_id=company_id,
                    payable_id=payable.id,
                    installment_id=installment.id,
                    supplier_id=payable.supplier_id,
                    amount=installment.amount,
                    currency=payable.currency,
                    due_date=installment.due_date,
                    payable_status=PayableStatus(payable.status),
                    installment_status=PayableInstallmentStatus(installment.status),
                    matching_status=MatchingGateStatus(matching.status),
                    matching_session_id=matching.id,
                    payable_created_by=payable.created_by,
                    payable_approved_by=payable.decision_by,
                    beneficiary=beneficiary,
                    has_unresolved_block=(
                        governance is not None
                        and (governance.fiscal_blocked or governance.purchasing_blocked)
                    ),
                    active_batch_id=await self._active_batch(company_id, installment.id),
                )
            )
        return tuple(values)

    async def _matching(
        self,
        company_id: UUID,
        payable_id: UUID,
    ) -> MatchingSessionModel | None:
        return cast(
            MatchingSessionModel | None,
            await self._session.scalar(
                select(MatchingSessionModel)
                .where(
                    MatchingSessionModel.company_id == company_id,
                    MatchingSessionModel.payable_id == payable_id,
                    MatchingSessionModel.status.in_(("MATCHED", "OVERRIDDEN")),
                )
                .order_by(
                    MatchingSessionModel.completed_at.desc().nullslast(),
                    MatchingSessionModel.id.desc(),
                )
                .limit(1)
            ),
        )

    async def _active_batch(
        self,
        company_id: UUID,
        installment_id: UUID,
    ) -> UUID | None:
        return cast(
            UUID | None,
            await self._session.scalar(
                select(PaymentBatchItemModel.payment_batch_id)
                .join(
                    PaymentBatchModel,
                    (PaymentBatchModel.company_id == PaymentBatchItemModel.company_id)
                    & (PaymentBatchModel.id == PaymentBatchItemModel.payment_batch_id),
                )
                .where(
                    PaymentBatchItemModel.company_id == company_id,
                    PaymentBatchItemModel.installment_id == installment_id,
                    PaymentBatchModel.status.in_(_ACTIVE_BATCH_STATUSES),
                )
                .limit(1)
            ),
        )


__all__ = ["PostgresTreasuryPaymentCandidateProvider"]
