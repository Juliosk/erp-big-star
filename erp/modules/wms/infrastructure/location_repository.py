"""Tenant-bound persistence and spatial queries for the WMS location hierarchy."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from erp.modules.inventory.infrastructure.warehouse_model import WarehouseLocationModel
from erp.modules.wms.domain.locations import (
    BinCapacity,
    BinDimensions,
    OccupancyStatus,
    StorageType,
    WarehouseAddress,
    WarehouseBin,
)
from erp.modules.wms.infrastructure.location_model import (
    WmsAisleModel,
    WmsBayModel,
    WmsBinCapacityModel,
    WmsBinModel,
    WmsLevelModel,
    WmsZoneModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


def _conflict(message: str) -> ApplicationError:
    return ApplicationError(code="WMS_LOCATION_CONFLICT", message=message, status_code=409)


def _bin(
    model: WmsBinModel,
    capacity: WmsBinCapacityModel,
    zone: WmsZoneModel,
    aisle: WmsAisleModel,
    bay: WmsBayModel,
    level: WmsLevelModel,
) -> WarehouseBin:
    return WarehouseBin(
        address=WarehouseAddress(
            company_id=model.company_id,
            warehouse_id=model.warehouse_id,
            zone=zone.code,
            aisle=aisle.code,
            rack=bay.code,
            shelf=level.code,
            bin=model.code,
        ),
        inventory_location_id=model.id,
        capacity=BinCapacity(
            dimensions=BinDimensions(capacity.width, capacity.depth, capacity.height),
            max_weight=capacity.max_weight,
            max_units=capacity.max_units,
        ),
        storage_type=StorageType(zone.storage_type),
        occupied_units=model.occupied_units,
        used_weight=model.used_weight,
        used_volume=model.used_volume,
        blocked=model.blocked,
        version=model.version,
    )


class WMSLocationRepository:
    """Persist full bin aggregates without owning the caller's transaction."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, aggregate: WarehouseBin, *, actor_id: UUID) -> WarehouseBin:
        self._validate_write(aggregate, actor_id)
        if aggregate.version != 1:
            raise ValueError("A new WMS bin must start at version one.")
        await self._require_inventory_location(aggregate)
        zone = await self._zone(aggregate, actor_id)
        aisle = await self._aisle(aggregate, zone.id, actor_id)
        bay = await self._bay(aggregate, aisle.id, actor_id)
        level = await self._level(aggregate, bay.id, actor_id)
        self._session.add(
            WmsBinModel(
                id=aggregate.inventory_location_id,
                company_id=self._company_id,
                warehouse_id=aggregate.address.warehouse_id,
                level_id=level.id,
                code=aggregate.address.bin,
                address_code=aggregate.address.code,
                occupied_units=aggregate.occupied_units,
                used_weight=aggregate.used_weight,
                used_volume=aggregate.used_volume,
                blocked=aggregate.blocked,
                version=aggregate.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_conflict("Bin address or inventory location already exists.")
        self._session.add(
            WmsBinCapacityModel(
                company_id=self._company_id,
                bin_id=aggregate.inventory_location_id,
                width=aggregate.capacity.dimensions.width,
                depth=aggregate.capacity.dimensions.depth,
                height=aggregate.capacity.dimensions.height,
                max_weight=aggregate.capacity.max_weight,
                max_units=aggregate.capacity.max_units,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_conflict("Bin capacity conflicts with its physical location.")
        return aggregate

    async def get(self, inventory_location_id: UUID) -> WarehouseBin | None:
        statement = self._base_statement().where(
            WmsBinModel.company_id == self._company_id,
            WmsBinModel.id == inventory_location_id,
        )
        row = (await self._session.execute(statement)).one_or_none()
        return None if row is None else _bin(row[0], row[1], row[2], row[3], row[4], row[5])

    async def get_for_update(self, inventory_location_id: UUID) -> WarehouseBin | None:
        statement = (
            self._base_statement()
            .where(
                WmsBinModel.company_id == self._company_id,
                WmsBinModel.id == inventory_location_id,
            )
            .with_for_update(of=WmsBinModel)
        )
        row = (await self._session.execute(statement)).one_or_none()
        return None if row is None else _bin(row[0], row[1], row[2], row[3], row[4], row[5])

    async def get_by_address(self, address: WarehouseAddress) -> WarehouseBin | None:
        if not isinstance(address, WarehouseAddress):
            raise TypeError("address must be a WarehouseAddress.")
        if address.company_id != self._company_id:
            return None
        statement = self._base_statement().where(
            WmsBinModel.company_id == self._company_id,
            WmsBinModel.warehouse_id == address.warehouse_id,
            WmsBinModel.address_code == address.code,
        )
        row = (await self._session.execute(statement)).one_or_none()
        return None if row is None else _bin(row[0], row[1], row[2], row[3], row[4], row[5])

    async def save(
        self,
        aggregate: WarehouseBin,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> WarehouseBin:
        self._validate_write(aggregate, actor_id)
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected_version must be a positive integer.")
        if aggregate.version != expected_version + 1:
            raise ValueError("save requires exactly one new bin version.")
        current = await self.get(aggregate.inventory_location_id)
        if (
            current is None
            or current.address != aggregate.address
            or current.capacity != aggregate.capacity
            or current.storage_type is not aggregate.storage_type
        ):
            raise OptimisticLockError(expected_version=expected_version)
        result = await self._session.execute(
            update(WmsBinModel)
            .where(
                WmsBinModel.company_id == self._company_id,
                WmsBinModel.id == aggregate.inventory_location_id,
                WmsBinModel.version == expected_version,
            )
            .values(
                occupied_units=aggregate.occupied_units,
                used_weight=aggregate.used_weight,
                used_volume=aggregate.used_volume,
                blocked=aggregate.blocked,
                version=aggregate.version,
                updated_at=datetime.now(UTC),
                updated_by=actor_id,
            )
            .returning(WmsBinModel.id)
            .execution_options(synchronize_session=False)
        )
        if result.scalar_one_or_none() is None:
            raise OptimisticLockError(expected_version=expected_version)
        return aggregate

    async def search_bins(
        self,
        *,
        warehouse_id: UUID | None = None,
        zone: str | None = None,
        storage_types: tuple[StorageType, ...] | None = None,
        occupancy_statuses: tuple[OccupancyStatus, ...] | None = None,
        min_available_units: int = 0,
        min_available_weight: Decimal = Decimal("0"),
        min_available_volume: Decimal = Decimal("0"),
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[WarehouseBin, ...]:
        self._validate_search(
            storage_types,
            occupancy_statuses,
            min_available_units,
            min_available_weight,
            min_available_volume,
            limit,
            offset,
        )
        statement = self._base_statement()
        if warehouse_id is not None:
            statement = statement.where(WmsBinModel.warehouse_id == warehouse_id)
        if zone is not None:
            statement = statement.where(WmsZoneModel.code == _coordinate(zone))
        if storage_types:
            statement = statement.where(
                WmsZoneModel.storage_type.in_(value.value for value in storage_types)
            )
        if occupancy_statuses:
            statement = statement.where(
                or_(
                    *(self._occupancy_expression(value) for value in occupancy_statuses)
                )
            )
        available_volume = (
            WmsBinCapacityModel.width
            * WmsBinCapacityModel.depth
            * WmsBinCapacityModel.height
            - WmsBinModel.used_volume
        )
        statement = statement.where(
            WmsBinCapacityModel.max_units - WmsBinModel.occupied_units
            >= min_available_units,
            WmsBinCapacityModel.max_weight - WmsBinModel.used_weight
            >= min_available_weight,
            available_volume >= min_available_volume,
        )
        if (
            min_available_units > 0
            or min_available_weight > 0
            or min_available_volume > 0
        ) and (
            not occupancy_statuses or OccupancyStatus.BLOCKED not in occupancy_statuses
        ):
            statement = statement.where(WmsBinModel.blocked.is_(False))
        rows = (
            await self._session.execute(
                statement.order_by(WmsBinModel.address_code).limit(limit).offset(offset)
            )
        ).all()
        return tuple(_bin(row[0], row[1], row[2], row[3], row[4], row[5]) for row in rows)

    def _base_statement(
        self,
    ) -> Select[
        tuple[
            WmsBinModel,
            WmsBinCapacityModel,
            WmsZoneModel,
            WmsAisleModel,
            WmsBayModel,
            WmsLevelModel,
        ]
    ]:
        return (
            select(
                WmsBinModel,
                WmsBinCapacityModel,
                WmsZoneModel,
                WmsAisleModel,
                WmsBayModel,
                WmsLevelModel,
            )
            .join(
                WmsBinCapacityModel,
                and_(
                    WmsBinCapacityModel.company_id == WmsBinModel.company_id,
                    WmsBinCapacityModel.bin_id == WmsBinModel.id,
                ),
            )
            .join(WmsLevelModel, WmsLevelModel.id == WmsBinModel.level_id)
            .join(WmsBayModel, WmsBayModel.id == WmsLevelModel.bay_id)
            .join(WmsAisleModel, WmsAisleModel.id == WmsBayModel.aisle_id)
            .join(WmsZoneModel, WmsZoneModel.id == WmsAisleModel.zone_id)
            .where(WmsBinModel.company_id == self._company_id)
            .execution_options(populate_existing=True)
        )

    async def _require_inventory_location(self, aggregate: WarehouseBin) -> None:
        exists = await self._session.scalar(
            select(WarehouseLocationModel.id).where(
                WarehouseLocationModel.company_id == self._company_id,
                WarehouseLocationModel.warehouse_id == aggregate.address.warehouse_id,
                WarehouseLocationModel.id == aggregate.inventory_location_id,
                WarehouseLocationModel.active.is_(True),
            )
        )
        if exists is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Active inventory location not found for the selected warehouse.",
                status_code=404,
            )

    async def _zone(self, aggregate: WarehouseBin, actor_id: UUID) -> WmsZoneModel:
        address = aggregate.address
        model = await self._session.scalar(
            select(WmsZoneModel).where(
                WmsZoneModel.company_id == self._company_id,
                WmsZoneModel.warehouse_id == address.warehouse_id,
                WmsZoneModel.code == address.zone,
            )
        )
        if model is not None:
            if model.storage_type != aggregate.storage_type.value:
                raise _conflict("A zone cannot mix different storage types.")
            return model
        model = WmsZoneModel(
            id=uuid4(),
            company_id=self._company_id,
            warehouse_id=address.warehouse_id,
            code=address.zone,
            storage_type=aggregate.storage_type.value,
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(model)
        await self._flush_conflict("Zone address already exists.")
        return model

    async def _aisle(
        self, aggregate: WarehouseBin, zone_id: UUID, actor_id: UUID
    ) -> WmsAisleModel:
        address = aggregate.address
        model = await self._session.scalar(
            select(WmsAisleModel).where(
                WmsAisleModel.company_id == self._company_id,
                WmsAisleModel.warehouse_id == address.warehouse_id,
                WmsAisleModel.zone_id == zone_id,
                WmsAisleModel.code == address.aisle,
            )
        )
        if model is not None:
            return model
        model = WmsAisleModel(
            id=uuid4(),
            company_id=self._company_id,
            warehouse_id=address.warehouse_id,
            zone_id=zone_id,
            code=address.aisle,
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(model)
        await self._flush_conflict("Aisle address already exists.")
        return model

    async def _bay(
        self, aggregate: WarehouseBin, aisle_id: UUID, actor_id: UUID
    ) -> WmsBayModel:
        address = aggregate.address
        model = await self._session.scalar(
            select(WmsBayModel).where(
                WmsBayModel.company_id == self._company_id,
                WmsBayModel.warehouse_id == address.warehouse_id,
                WmsBayModel.aisle_id == aisle_id,
                WmsBayModel.code == address.rack,
            )
        )
        if model is not None:
            return model
        model = WmsBayModel(
            id=uuid4(),
            company_id=self._company_id,
            warehouse_id=address.warehouse_id,
            aisle_id=aisle_id,
            code=address.rack,
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(model)
        await self._flush_conflict("Bay address already exists.")
        return model

    async def _level(
        self, aggregate: WarehouseBin, bay_id: UUID, actor_id: UUID
    ) -> WmsLevelModel:
        address = aggregate.address
        model = await self._session.scalar(
            select(WmsLevelModel).where(
                WmsLevelModel.company_id == self._company_id,
                WmsLevelModel.warehouse_id == address.warehouse_id,
                WmsLevelModel.bay_id == bay_id,
                WmsLevelModel.code == address.shelf,
            )
        )
        if model is not None:
            return model
        model = WmsLevelModel(
            id=uuid4(),
            company_id=self._company_id,
            warehouse_id=address.warehouse_id,
            bay_id=bay_id,
            code=address.shelf,
            version=1,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(model)
        await self._flush_conflict("Level address already exists.")
        return model

    @staticmethod
    def _occupancy_expression(status: OccupancyStatus) -> ColumnElement[bool]:
        volume = (
            WmsBinCapacityModel.width
            * WmsBinCapacityModel.depth
            * WmsBinCapacityModel.height
        )
        if status is OccupancyStatus.BLOCKED:
            return WmsBinModel.blocked.is_(True)
        if status is OccupancyStatus.EMPTY:
            return and_(WmsBinModel.blocked.is_(False), WmsBinModel.occupied_units == 0)
        full = or_(
            WmsBinModel.occupied_units == WmsBinCapacityModel.max_units,
            WmsBinModel.used_weight == WmsBinCapacityModel.max_weight,
            WmsBinModel.used_volume == volume,
        )
        if status is OccupancyStatus.FULL:
            return and_(WmsBinModel.blocked.is_(False), full)
        return and_(
            WmsBinModel.blocked.is_(False),
            WmsBinModel.occupied_units > 0,
            ~full,
        )

    def _validate_write(self, aggregate: WarehouseBin, actor_id: UUID) -> None:
        if not isinstance(aggregate, WarehouseBin):
            raise TypeError("aggregate must be a WarehouseBin.")
        if aggregate.address.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The WMS bin is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise ValueError("actor_id must be a non-zero UUID.")

    @staticmethod
    def _validate_search(
        storage_types: tuple[StorageType, ...] | None,
        occupancy_statuses: tuple[OccupancyStatus, ...] | None,
        min_available_units: int,
        min_available_weight: Decimal,
        min_available_volume: Decimal,
        limit: int,
        offset: int,
    ) -> None:
        if storage_types is not None and (
            not isinstance(storage_types, tuple)
            or any(not isinstance(value, StorageType) for value in storage_types)
        ):
            raise ValueError("storage_types must contain StorageType values.")
        if occupancy_statuses is not None and (
            not isinstance(occupancy_statuses, tuple)
            or any(not isinstance(value, OccupancyStatus) for value in occupancy_statuses)
        ):
            raise ValueError("occupancy_statuses must contain OccupancyStatus values.")
        if type(min_available_units) is not int or min_available_units < 0:
            raise ValueError("min_available_units must be a non-negative integer.")
        for value in (min_available_weight, min_available_volume):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError("Available physical measures must be finite and non-negative.")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer between 1 and 200.")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer.")

    async def _flush_conflict(self, message: str) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) in {"23503", "23505", "23514"}:
                raise _conflict(message) from error
            raise


def _coordinate(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("zone must be text.")
    normalized = value.strip().upper()
    if re.fullmatch(r"[A-Z0-9][A-Z0-9_]{0,15}", normalized) is None:
        raise ValueError("zone must contain 1 to 16 canonical characters.")
    return normalized


__all__ = ["WMSLocationRepository", "_bin"]
