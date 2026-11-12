"""PostgreSQL projection for governed payment requests."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from erp.modules.finance.application.payment_cockpit import (
    FinanceCockpitPayment,
    FinanceCockpitSnapshot,
)
from erp.modules.finance.domain import PaymentRequest, PaymentRequestStatus
from erp.modules.finance.infrastructure.payment_request_repository import (
    PaymentRequestRepository,
)
from erp.platform.database import Database


class PostgresFinanceCockpitReader:
    """Load payment governance rows through the tenant-bound repository."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def load(
        self,
        company_id: UUID,
        *,
        generated_at: datetime,
        limit: int,
    ) -> FinanceCockpitSnapshot:
        async with self._database.session() as session:
            requests = await PaymentRequestRepository(
                session,
                company_id=company_id,
            ).list(limit=limit)
        return FinanceCockpitSnapshot(
            company_id=company_id,
            generated_at=generated_at,
            total_requests=len(requests),
            draft_requests=_count(requests, PaymentRequestStatus.DRAFT),
            pending_requests=_count(requests, PaymentRequestStatus.PENDING_APPROVAL),
            approved_requests=_count(requests, PaymentRequestStatus.APPROVED),
            batched_requests=_count(requests, PaymentRequestStatus.BATCHED),
            rejected_requests=_count(requests, PaymentRequestStatus.REJECTED),
            pending_amount=_amount(requests, PaymentRequestStatus.PENDING_APPROVAL),
            approved_amount=_amount(requests, PaymentRequestStatus.APPROVED),
            payments=tuple(
                FinanceCockpitPayment(
                    id=request.id,
                    code=request.code,
                    status=request.status.value,
                    scheduled_on=request.scheduled_on,
                    purpose=request.purpose,
                    item_count=len(request.items),
                    total_amount=request.total_amount,
                    currency=request.currency,
                    requested_by=request.requested_by,
                    approved_by=request.approved_by,
                    version=request.version,
                )
                for request in requests
            ),
        )


def _count(
    requests: tuple[PaymentRequest, ...],
    status: PaymentRequestStatus,
) -> int:
    return sum(request.status is status for request in requests)


def _amount(
    requests: tuple[PaymentRequest, ...],
    status: PaymentRequestStatus,
) -> Decimal:
    return sum(
        (request.total_amount for request in requests if request.status is status),
        start=Decimal("0.00"),
    )


__all__ = ["PostgresFinanceCockpitReader"]
