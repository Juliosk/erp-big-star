"""PostgreSQL projection for the procurement RFQ cockpit."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from erp.modules.procurement.application.rfq_cockpit import (
    ProcurementCockpitRfq,
    ProcurementCockpitSnapshot,
)
from erp.modules.procurement.domain import RequestForQuotation, RequestForQuotationStatus
from erp.modules.procurement.infrastructure.rfq_repository import (
    RequestForQuotationRepository,
)
from erp.platform.database import Database


class PostgresProcurementCockpitReader:
    """Load the sourcing queue through the aggregate repository."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def load(
        self,
        company_id: UUID,
        *,
        generated_at: datetime,
        limit: int,
    ) -> ProcurementCockpitSnapshot:
        async with self._database.session() as session:
            rfqs = await RequestForQuotationRepository(
                session,
                company_id=company_id,
            ).list(limit=limit)
        return ProcurementCockpitSnapshot(
            company_id=company_id,
            generated_at=generated_at,
            total_rfqs=len(rfqs),
            draft_rfqs=_count(rfqs, RequestForQuotationStatus.DRAFT),
            open_rfqs=_count(rfqs, RequestForQuotationStatus.OPEN),
            closed_rfqs=_count(rfqs, RequestForQuotationStatus.CLOSED),
            awarded_rfqs=_count(rfqs, RequestForQuotationStatus.AWARDED),
            cancelled_rfqs=_count(rfqs, RequestForQuotationStatus.CANCELLED),
            rfqs=tuple(_row(rfq) for rfq in rfqs),
        )


def _count(
    rfqs: tuple[RequestForQuotation, ...],
    status: RequestForQuotationStatus,
) -> int:
    return sum(rfq.status is status for rfq in rfqs)


def _row(rfq: RequestForQuotation) -> ProcurementCockpitRfq:
    currencies = {quote.currency for quote in rfq.supplier_quotes}
    comparable_currency = next(iter(currencies)) if len(currencies) == 1 else None
    lowest: Decimal | None = None
    if comparable_currency is not None:
        lowest = min(quote.total_amount for quote in rfq.supplier_quotes)
    return ProcurementCockpitRfq(
        id=rfq.id,
        code=rfq.code,
        status=rfq.status.value,
        response_deadline=rfq.response_deadline,
        item_count=len(rfq.items),
        invited_supplier_count=len(rfq.invited_supplier_ids),
        quote_count=len(rfq.supplier_quotes),
        comparable_quote_currency=comparable_currency,
        lowest_quote_amount=lowest,
        awarded_supplier_id=None if rfq.award is None else rfq.award.supplier_id,
        version=rfq.version,
    )


__all__ = ["PostgresProcurementCockpitReader"]
