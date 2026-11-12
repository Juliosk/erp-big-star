"""Procurement cockpit HTTP response contracts."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ProcurementCockpitRfqResponse(BaseModel):
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


class ProcurementCockpitResponse(BaseModel):
    company_id: UUID
    generated_at: datetime
    total_rfqs: int
    draft_rfqs: int
    open_rfqs: int
    closed_rfqs: int
    awarded_rfqs: int
    cancelled_rfqs: int
    rfqs: list[ProcurementCockpitRfqResponse]


__all__ = ["ProcurementCockpitResponse", "ProcurementCockpitRfqResponse"]
