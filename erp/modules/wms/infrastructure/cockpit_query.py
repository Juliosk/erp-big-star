"""PostgreSQL read model for the WMS physical operations cockpit."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select

from erp.modules.wms.application.cockpit import (
    WmsCockpitSnapshot,
    WmsCockpitWave,
    WmsDispatchQueueEntry,
    WmsZoneOccupancy,
)
from erp.modules.wms.infrastructure.location_model import (
    WmsAisleModel,
    WmsBayModel,
    WmsBinCapacityModel,
    WmsBinModel,
    WmsLevelModel,
    WmsZoneModel,
)
from erp.modules.wms.infrastructure.picking_packing_model import (
    WmsPickingItemModel,
    WmsPickingWaveModel,
)
from erp.platform.database import Database

_HUNDRED = Decimal("100")
_PERCENT = Decimal("0.01")


class PostgresWmsCockpitReader:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def load(
        self,
        company_id: UUID,
        *,
        as_of: datetime,
        limit: int,
    ) -> WmsCockpitSnapshot:
        async with self._database.session() as session:
            waves = list(
                (
                    await session.scalars(
                        select(WmsPickingWaveModel)
                        .where(WmsPickingWaveModel.company_id == company_id)
                        .order_by(WmsPickingWaveModel.updated_at.desc(), WmsPickingWaveModel.id)
                        .limit(limit)
                    )
                ).all()
            )
            wave_ids = [wave.id for wave in waves]
            items = (
                list(
                    (
                        await session.scalars(
                            select(WmsPickingItemModel)
                            .where(
                                WmsPickingItemModel.company_id == company_id,
                                WmsPickingItemModel.wave_id.in_(wave_ids),
                            )
                            .order_by(
                                WmsPickingItemModel.wave_id,
                                WmsPickingItemModel.route_sequence,
                            )
                        )
                    ).all()
                )
                if wave_ids
                else []
            )
            zones = list(
                (
                    await session.scalars(
                        select(WmsZoneModel)
                        .where(WmsZoneModel.company_id == company_id)
                        .order_by(WmsZoneModel.code)
                    )
                ).all()
            )
            bin_rows = list(
                (
                    await session.execute(
                        select(WmsZoneModel.id, WmsBinModel, WmsBinCapacityModel)
                        .join(
                            WmsAisleModel,
                            (WmsAisleModel.company_id == WmsZoneModel.company_id)
                            & (WmsAisleModel.zone_id == WmsZoneModel.id),
                        )
                        .join(
                            WmsBayModel,
                            (WmsBayModel.company_id == WmsAisleModel.company_id)
                            & (WmsBayModel.aisle_id == WmsAisleModel.id),
                        )
                        .join(
                            WmsLevelModel,
                            (WmsLevelModel.company_id == WmsBayModel.company_id)
                            & (WmsLevelModel.bay_id == WmsBayModel.id),
                        )
                        .join(
                            WmsBinModel,
                            (WmsBinModel.company_id == WmsLevelModel.company_id)
                            & (WmsBinModel.level_id == WmsLevelModel.id),
                        )
                        .join(
                            WmsBinCapacityModel,
                            (WmsBinCapacityModel.company_id == WmsBinModel.company_id)
                            & (WmsBinCapacityModel.bin_id == WmsBinModel.id),
                        )
                        .where(WmsZoneModel.company_id == company_id)
                    )
                ).all()
            )

        items_by_wave: defaultdict[UUID, list[WmsPickingItemModel]] = defaultdict(list)
        for item in items:
            items_by_wave[item.wave_id].append(item)
        cockpit_waves = tuple(_wave(wave, items_by_wave[wave.id]) for wave in waves)
        occupancy = _zones(
            zones,
            [(row[0], row[1], row[2]) for row in bin_rows],
        )
        total_units = sum(zone.occupied_units for zone in occupancy)
        max_units = sum(zone.max_units for zone in occupancy)
        return WmsCockpitSnapshot(
            company_id=company_id,
            generated_at=as_of,
            waves=cockpit_waves,
            zones=occupancy,
            dispatch_queue=tuple(
                _queue(wave, items_by_wave[wave.id])
                for wave in waves
                if wave.status != "MANIFESTED"
            ),
            total_bins=sum(zone.bin_count for zone in occupancy),
            blocked_bins=sum(zone.blocked_bins for zone in occupancy),
            occupancy_percent=_ratio(total_units, max_units),
        )


def _wave(
    wave: WmsPickingWaveModel,
    items: list[WmsPickingItemModel],
) -> WmsCockpitWave:
    picked = sum(item.status in {"PICKED", "PACKED"} for item in items)
    packed = sum(item.status == "PACKED" for item in items)
    progress = _ratio(picked + packed, len(items) * 2)
    next_item = next((item for item in items if item.status != "PACKED"), None)
    return WmsCockpitWave(
        id=wave.id,
        code=wave.code,
        warehouse_id=wave.warehouse_id,
        status=wave.status,
        item_count=len(items),
        picked_items=picked,
        packed_items=packed,
        progress_percent=progress,
        first_address=None if not items else items[0].route_address,
        next_address=None if next_item is None else next_item.route_address,
        manifest_number=wave.manifest_number,
        updated_at=wave.updated_at,
    )


def _queue(
    wave: WmsPickingWaveModel,
    items: list[WmsPickingItemModel],
) -> WmsDispatchQueueEntry:
    return WmsDispatchQueueEntry(
        wave_id=wave.id,
        wave_code=wave.code,
        status=wave.status,
        pending_pick_items=sum(item.status == "OPEN" for item in items),
        pending_pack_items=sum(item.status == "PICKED" for item in items),
        ready_items=sum(item.status == "PACKED" for item in items),
        manifest_number=wave.manifest_number,
    )


def _zones(
    zones: list[WmsZoneModel],
    rows: list[tuple[UUID, WmsBinModel, WmsBinCapacityModel]],
) -> tuple[WmsZoneOccupancy, ...]:
    by_zone: defaultdict[UUID, list[tuple[WmsBinModel, WmsBinCapacityModel]]] = defaultdict(list)
    for zone_id, bin_model, capacity in rows:
        by_zone[zone_id].append((bin_model, capacity))
    result: list[WmsZoneOccupancy] = []
    for zone in zones:
        bins = by_zone[zone.id]
        occupied_units = sum(bin_model.occupied_units for bin_model, _ in bins)
        max_units = sum(capacity.max_units for _, capacity in bins)
        result.append(
            WmsZoneOccupancy(
                zone_id=zone.id,
                code=zone.code,
                storage_type=zone.storage_type,
                bin_count=len(bins),
                occupied_bins=sum(bin_model.occupied_units > 0 for bin_model, _ in bins),
                blocked_bins=sum(bin_model.blocked for bin_model, _ in bins),
                occupied_units=occupied_units,
                max_units=max_units,
                occupancy_percent=_ratio(occupied_units, max_units),
            )
        )
    return tuple(result)


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0.00")
    return (Decimal(numerator) / Decimal(denominator) * _HUNDRED).quantize(
        _PERCENT, rounding=ROUND_HALF_UP
    )


__all__ = ["PostgresWmsCockpitReader"]
