"""PostgreSQL source adapters for Cash Flow composition."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application.cash_flow import BankCashPosition
from erp.modules.finance.domain import (
    CashAmount,
    CashFlowCategory,
    CashFlowCertainty,
    CashFlowDateHorizon,
    CashFlowDirection,
    CashFlowItem,
    CashFlowOrigin,
)
from erp.modules.finance.infrastructure.bank_statement_model import BankStatementModel
from erp.modules.finance.infrastructure.payable_model import (
    PayableInstallmentModel,
    PayableModel,
)
from erp.modules.finance.infrastructure.treasury_model import (
    PaymentBatchItemModel,
    PaymentBatchModel,
)

_COMMITTED_PAYABLE_STATUSES = ("APPROVED", "SCHEDULED")
_UNPAID_INSTALLMENT_STATUSES = ("OPEN", "SCHEDULED")
_ACTIVE_BATCH_STATUSES = ("APPROVED", "RELEASED", "SUBMITTED")


class PostgresBankPositionProvider:
    """Read the latest known statement closing balance per bank account."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def positions(
        self,
        *,
        company_id: UUID,
        as_of: date,
        currency: str,
    ) -> tuple[BankCashPosition, ...]:
        if currency != "BRL":
            return ()
        knowledge_cutoff = datetime.combine(as_of + timedelta(days=1), time.min, UTC)
        ranked = (
            select(
                BankStatementModel.company_id.label("company_id"),
                BankStatementModel.bank_account_id.label("bank_account_id"),
                BankStatementModel.id.label("statement_id"),
                BankStatementModel.period_end.label("as_of"),
                BankStatementModel.closing_balance.label("closing_balance"),
                func.row_number()
                .over(
                    partition_by=BankStatementModel.bank_account_id,
                    order_by=(
                        BankStatementModel.period_end.desc(),
                        BankStatementModel.imported_at.desc(),
                        BankStatementModel.id.desc(),
                    ),
                )
                .label("position_rank"),
            )
            .where(
                BankStatementModel.company_id == company_id,
                BankStatementModel.period_end <= as_of,
                BankStatementModel.imported_at < knowledge_cutoff,
                BankStatementModel.closing_balance.is_not(None),
            )
            .subquery()
        )
        rows = (
            await self._session.execute(
                select(
                    ranked.c.company_id,
                    ranked.c.bank_account_id,
                    ranked.c.statement_id,
                    ranked.c.as_of,
                    ranked.c.closing_balance,
                )
                .where(ranked.c.position_rank == 1)
                .order_by(ranked.c.bank_account_id)
            )
        ).all()
        return tuple(
            BankCashPosition(
                company_id=cast(UUID, row.company_id),
                bank_account_id=cast(UUID, row.bank_account_id),
                statement_id=cast(UUID, row.statement_id),
                as_of=cast(date, row.as_of),
                balance=CashAmount(cast(Decimal, row.closing_balance), "BRL"),
            )
            for row in rows
        )


class PostgresPayableCommitmentProvider:
    """Map approved M12 installments and active Treasury batches to committed cash."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commitments(
        self,
        *,
        company_id: UUID,
        horizon: CashFlowDateHorizon,
        currency: str,
    ) -> tuple[CashFlowItem, ...]:
        batch_dates = (
            select(
                PaymentBatchItemModel.company_id.label("company_id"),
                PaymentBatchItemModel.installment_id.label("installment_id"),
                func.min(PaymentBatchModel.scheduled_date).label("scheduled_on"),
            )
            .join(
                PaymentBatchModel,
                (PaymentBatchModel.company_id == PaymentBatchItemModel.company_id)
                & (PaymentBatchModel.id == PaymentBatchItemModel.payment_batch_id),
            )
            .where(
                PaymentBatchItemModel.company_id == company_id,
                PaymentBatchModel.status.in_(_ACTIVE_BATCH_STATUSES),
            )
            .group_by(PaymentBatchItemModel.company_id, PaymentBatchItemModel.installment_id)
            .subquery()
        )
        contractual_on = func.coalesce(
            batch_dates.c.scheduled_on, PayableInstallmentModel.due_date
        )
        effective_on = func.greatest(contractual_on, horizon.start_on)
        rows = (
            await self._session.execute(
                select(
                    PayableInstallmentModel.id.label("installment_id"),
                    PayableInstallmentModel.company_id.label("company_id"),
                    PayableInstallmentModel.amount.label("amount"),
                    PayableModel.currency.label("currency"),
                    effective_on.label("occurs_on"),
                )
                .join(
                    PayableModel,
                    (PayableModel.company_id == PayableInstallmentModel.company_id)
                    & (PayableModel.id == PayableInstallmentModel.payable_id),
                )
                .outerjoin(
                    batch_dates,
                    (batch_dates.c.company_id == PayableInstallmentModel.company_id)
                    & (batch_dates.c.installment_id == PayableInstallmentModel.id),
                )
                .where(
                    PayableInstallmentModel.company_id == company_id,
                    PayableModel.currency == currency,
                    PayableModel.status.in_(_COMMITTED_PAYABLE_STATUSES),
                    PayableInstallmentModel.status.in_(_UNPAID_INSTALLMENT_STATUSES),
                    contractual_on <= horizon.end_on,
                )
                .order_by(effective_on, PayableInstallmentModel.id)
            )
        ).all()
        return tuple(
            CashFlowItem(
                company_id=cast(UUID, row.company_id),
                amount=CashAmount(cast(Decimal, row.amount), cast(str, row.currency)),
                occurs_on=cast(date, row.occurs_on),
                direction=CashFlowDirection.OUTFLOW,
                category=CashFlowCategory.OPERATING,
                certainty=CashFlowCertainty.COMMITTED,
                origin=CashFlowOrigin.PAYABLE_INSTALLMENT,
                reference_id=cast(UUID, row.installment_id),
            )
            for row in rows
        )


__all__ = ["PostgresBankPositionProvider", "PostgresPayableCommitmentProvider"]
