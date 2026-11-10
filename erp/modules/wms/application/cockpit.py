"""Read-only contracts for the WMS physical operations cockpit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.wms.application.permissions import WMS_INVENTORY_READ, WmsAuthorization


@dataclass(frozen=True, slots=True)
class WmsCockpitWave:
    id: UUID
    code: str
    warehouse_id: UUID
    status: str
    item_count: int
    picked_items: int
    packed_items: int
    progress_percent: Decimal
    first_address: str | None
    next_address: str | None
    manifest_number: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WmsZoneOccupancy:
    zone_id: UUID
    code: str
    storage_type: str
    bin_count: int
    occupied_bins: int
    blocked_bins: int
    occupied_units: int
    max_units: int
    occupancy_percent: Decimal


@dataclass(frozen=True, slots=True)
class WmsDispatchQueueEntry:
    wave_id: UUID
    wave_code: str
    status: str
    pending_pick_items: int
    pending_pack_items: int
    ready_items: int
    manifest_number: str | None


@dataclass(frozen=True, slots=True)
class WmsCockpitSnapshot:
    company_id: UUID
    generated_at: datetime
    waves: tuple[WmsCockpitWave, ...]
    zones: tuple[WmsZoneOccupancy, ...]
    dispatch_queue: tuple[WmsDispatchQueueEntry, ...]
    total_bins: int
    blocked_bins: int
    occupancy_percent: Decimal


class WmsCockpitReader(Protocol):
    async def load(
        self,
        company_id: UUID,
        *,
        as_of: datetime,
        limit: int,
    ) -> WmsCockpitSnapshot: ...


class WmsCockpitService:
    """Authorize and load a tenant-bound warehouse execution snapshot."""

    def __init__(self, reader: WmsCockpitReader, authorization: WmsAuthorization) -> None:
        self._reader = reader
        self._authorization = authorization

    async def snapshot(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        limit: int = 50,
        as_of: datetime | None = None,
    ) -> WmsCockpitSnapshot:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200.")
        await self._authorization.require(context, company_id, WMS_INVENTORY_READ)
        instant = as_of or datetime.now(UTC)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware.")
        return await self._reader.load(company_id, as_of=instant, limit=limit)


__all__ = [
    "WmsCockpitReader",
    "WmsCockpitService",
    "WmsCockpitSnapshot",
    "WmsCockpitWave",
    "WmsDispatchQueueEntry",
    "WmsZoneOccupancy",
]
