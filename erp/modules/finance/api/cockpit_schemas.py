"""Finance cockpit HTTP response contracts."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class FinanceCockpitPaymentResponse(BaseModel):
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


class FinanceCockpitResponse(BaseModel):
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
    payments: list[FinanceCockpitPaymentResponse]


__all__ = ["FinanceCockpitPaymentResponse", "FinanceCockpitResponse"]
