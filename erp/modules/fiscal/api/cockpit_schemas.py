"""Fiscal cockpit HTTP response contracts."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class FiscalCockpitRuleResponse(BaseModel):
    id: UUID
    code: str
    version_code: str
    status: str
    flow: str
    ncm: str
    cfop: str
    effective_from: date
    effective_until: date | None
    icms_rate: Decimal
    pis_rate: Decimal
    cofins_rate: Decimal
    ipi_rate: Decimal
    version: int


class FiscalCockpitResponse(BaseModel):
    company_id: UUID
    generated_at: datetime
    total_rules: int
    draft_rules: int
    active_rules: int
    retired_rules: int
    rules: list[FiscalCockpitRuleResponse]


__all__ = ["FiscalCockpitResponse", "FiscalCockpitRuleResponse"]
