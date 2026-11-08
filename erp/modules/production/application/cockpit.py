"""Read-only Production cockpit contracts and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.production.application.permissions import (
    PRODUCTION_SHOP_FLOOR_READ,
    ProductionAuthorization,
)


@dataclass(frozen=True, slots=True)
class ProductionCockpitOrder:
    id: UUID
    order_number: str
    product_id: UUID
    status: str
    planned_quantity: Decimal
    planned_uom: str
    good_quantity: Decimal
    scrap_quantity: Decimal
    progress_percent: Decimal
    completed_operations: int
    total_operations: int
    current_operation: str | None
    current_work_center: str | None
    planned_start_on: date
    due_on: date
    synchronization_pending: bool
    last_synchronization_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProductionWorkCenterLoad:
    code: str
    capabilities: tuple[str, ...]
    planned_minutes: Decimal
    capacity_minutes: Decimal
    load_percent: Decimal
    active_operations: int
    state: str


@dataclass(frozen=True, slots=True)
class ProductionCockpitAlert:
    severity: str
    alert_type: str
    title: str
    message: str
    production_order_id: UUID | None = None
    work_center_code: str | None = None


@dataclass(frozen=True, slots=True)
class ProductionCockpitSnapshot:
    company_id: UUID
    generated_at: datetime
    standard_shift_minutes: int
    orders: tuple[ProductionCockpitOrder, ...]
    work_centers: tuple[ProductionWorkCenterLoad, ...]
    alerts: tuple[ProductionCockpitAlert, ...]
    pending_synchronizations: int


class ProductionCockpitReader(Protocol):
    async def load(
        self,
        company_id: UUID,
        *,
        as_of: datetime,
        limit: int,
    ) -> ProductionCockpitSnapshot: ...


class ProductionCockpitService:
    """Authorize and load a tenant-scoped industrial operations snapshot."""

    def __init__(
        self,
        reader: ProductionCockpitReader,
        authorization: ProductionAuthorization,
    ) -> None:
        self._reader = reader
        self._authorization = authorization

    async def snapshot(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        limit: int = 50,
        as_of: datetime | None = None,
    ) -> ProductionCockpitSnapshot:
        if type(limit) is not int or limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200.")
        await self._authorization.require(
            context,
            company_id,
            PRODUCTION_SHOP_FLOOR_READ,
        )
        instant = as_of or datetime.now(UTC)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware.")
        return await self._reader.load(company_id, as_of=instant, limit=limit)


__all__ = [
    "ProductionCockpitAlert",
    "ProductionCockpitOrder",
    "ProductionCockpitReader",
    "ProductionCockpitService",
    "ProductionCockpitSnapshot",
    "ProductionWorkCenterLoad",
]
