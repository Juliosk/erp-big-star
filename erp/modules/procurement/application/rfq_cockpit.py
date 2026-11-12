"""Read-only RFQ cockpit contracts and orchestration."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.procurement.application.permissions import (
    PROCUREMENT_RFQ_READ,
    ProcurementAuthorization,
)


@dataclass(frozen=True, slots=True)
class ProcurementCockpitRfq:
    id: UUID
    code: str
    status: str
    response_deadline: date
    item_count: int
    invited_supplier_count: int
    quote_count: int
    comparable_quote_currency: str | None
    lowest_quote_amount: Decimal | None
    awarded_supplier_id: UUID | None
    version: int


@dataclass(frozen=True, slots=True)
class ProcurementCockpitSnapshot:
    company_id: UUID
    generated_at: datetime
    total_rfqs: int
    draft_rfqs: int
    open_rfqs: int
    closed_rfqs: int
    awarded_rfqs: int
    cancelled_rfqs: int
    rfqs: tuple[ProcurementCockpitRfq, ...]


class ProcurementCockpitReader(Protocol):
    async def load(
        self,
        company_id: UUID,
        *,
        generated_at: datetime,
        limit: int,
    ) -> ProcurementCockpitSnapshot: ...


class ProcurementCockpitService:
    """Authorize and return the tenant-bound sourcing competition queue."""

    def __init__(
        self,
        reader: ProcurementCockpitReader,
        authorization: ProcurementAuthorization,
    ) -> None:
        self._reader = reader
        self._authorization = authorization

    async def snapshot(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        limit: int = 100,
    ) -> ProcurementCockpitSnapshot:
        _limit(limit)
        await self._authorization.require(context, company_id, PROCUREMENT_RFQ_READ)
        return await self._reader.load(
            company_id,
            generated_at=datetime.now(UTC),
            limit=limit,
        )


def _limit(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")


__all__ = [
    "ProcurementCockpitReader",
    "ProcurementCockpitRfq",
    "ProcurementCockpitService",
    "ProcurementCockpitSnapshot",
]
