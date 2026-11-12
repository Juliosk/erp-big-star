"""Read-only fiscal tax-rule cockpit contracts and orchestration."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.fiscal.application.permissions import (
    FISCAL_TAX_RULE_READ,
    FiscalAuthorization,
)


@dataclass(frozen=True, slots=True)
class FiscalCockpitRule:
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


@dataclass(frozen=True, slots=True)
class FiscalCockpitSnapshot:
    company_id: UUID
    generated_at: datetime
    total_rules: int
    draft_rules: int
    active_rules: int
    retired_rules: int
    rules: tuple[FiscalCockpitRule, ...]


class FiscalCockpitReader(Protocol):
    async def load(
        self,
        company_id: UUID,
        *,
        generated_at: datetime,
        limit: int,
    ) -> FiscalCockpitSnapshot: ...


class FiscalCockpitService:
    """Authorize and return one tenant-bound tax governance snapshot."""

    def __init__(
        self,
        reader: FiscalCockpitReader,
        authorization: FiscalAuthorization,
    ) -> None:
        self._reader = reader
        self._authorization = authorization

    async def snapshot(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        limit: int = 100,
    ) -> FiscalCockpitSnapshot:
        _limit(limit)
        await self._authorization.require(context, company_id, FISCAL_TAX_RULE_READ)
        return await self._reader.load(
            company_id,
            generated_at=datetime.now(UTC),
            limit=limit,
        )


def _limit(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")


__all__ = [
    "FiscalCockpitReader",
    "FiscalCockpitRule",
    "FiscalCockpitService",
    "FiscalCockpitSnapshot",
]
