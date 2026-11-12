"""Read-only governed payment-request cockpit contracts."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.finance.application.permissions import (
    FINANCE_TREASURY_READ,
    FinanceAuthorization,
)


@dataclass(frozen=True, slots=True)
class FinanceCockpitPayment:
    id: UUID
    code: str
    status: str
    scheduled_on: date
    purpose: str
    item_count: int
    total_amount: Decimal
    currency: str
    requested_by: UUID
    approved_by: UUID | None
    version: int


@dataclass(frozen=True, slots=True)
class FinanceCockpitSnapshot:
    company_id: UUID
    generated_at: datetime
    total_requests: int
    draft_requests: int
    pending_requests: int
    approved_requests: int
    batched_requests: int
    rejected_requests: int
    pending_amount: Decimal
    approved_amount: Decimal
    payments: tuple[FinanceCockpitPayment, ...]


class FinanceCockpitReader(Protocol):
    async def load(
        self,
        company_id: UUID,
        *,
        generated_at: datetime,
        limit: int,
    ) -> FinanceCockpitSnapshot: ...


class FinanceCockpitService:
    """Authorize and return the tenant-bound payment governance queue."""

    def __init__(
        self,
        reader: FinanceCockpitReader,
        authorization: FinanceAuthorization,
    ) -> None:
        self._reader = reader
        self._authorization = authorization

    async def snapshot(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        limit: int = 100,
    ) -> FinanceCockpitSnapshot:
        _limit(limit)
        await self._authorization.require(context, company_id, FINANCE_TREASURY_READ)
        return await self._reader.load(
            company_id,
            generated_at=datetime.now(UTC),
            limit=limit,
        )


def _limit(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")


__all__ = [
    "FinanceCockpitPayment",
    "FinanceCockpitReader",
    "FinanceCockpitService",
    "FinanceCockpitSnapshot",
]
