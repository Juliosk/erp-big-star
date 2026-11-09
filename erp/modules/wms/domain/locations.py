"""Pure physical layout and putaway proposals, independent from the M5 ledger."""

import re
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from enum import StrEnum
from uuid import UUID


class WmsLocationError(ValueError):
    code = "INVALID_WMS_LOCATION"


class BinCapacityExceededError(WmsLocationError):
    code = "BIN_CAPACITY_EXCEEDED"


class PutawayZoneError(WmsLocationError):
    code = "PUTAWAY_ZONE_FORBIDDEN"


class StorageType(StrEnum):
    PICKING = "PICKING"
    RESERVE = "RESERVE"
    DAMAGED = "DAMAGED"
    QUARANTINE = "QUARANTINE"


class StockCondition(StrEnum):
    AVAILABLE = "AVAILABLE"
    DAMAGED = "DAMAGED"
    QUARANTINE = "QUARANTINE"


class OccupancyStatus(StrEnum):
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    FULL = "FULL"
    BLOCKED = "BLOCKED"


def _identity(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise WmsLocationError("Identity must be a non-zero UUID.")


def _coordinate(value: str) -> str:
    if not isinstance(value, str):
        raise WmsLocationError("Coordinate must be text.")
    normalized = value.strip().upper()
    if re.fullmatch(r"[A-Z0-9][A-Z0-9_]{0,15}", normalized) is None:
        raise WmsLocationError("Coordinate must contain 1 to 16 ASCII code characters.")
    return normalized


def _amount(value: Decimal, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise WmsLocationError("A finite Decimal is required.")
    if value < 0 or (positive and value == 0):
        raise WmsLocationError("Physical measure is outside its permitted range.")
    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)
    if exponent < -6 or value >= Decimal("1000000"):
        raise WmsLocationError("Physical measure exceeds supported precision/range.")


@dataclass(frozen=True, slots=True)
class WarehouseAddress:
    company_id: UUID
    warehouse_id: UUID
    zone: str
    aisle: str
    rack: str
    shelf: str
    bin: str

    def __post_init__(self) -> None:
        _identity(self.company_id)
        _identity(self.warehouse_id)
        for field in ("zone", "aisle", "rack", "shelf", "bin"):
            object.__setattr__(self, field, _coordinate(getattr(self, field)))

    @property
    def code(self) -> str:
        return "/".join((self.zone, self.aisle, self.rack, self.shelf, self.bin))

    @property
    def key(self) -> tuple[UUID, UUID, str]:
        return self.company_id, self.warehouse_id, self.code

    @classmethod
    def parse(cls, *, company_id: UUID, warehouse_id: UUID, code: str) -> WarehouseAddress:
        if not isinstance(code, str) or len(code.split("/")) != 5:
            raise WmsLocationError("Address requires zone/aisle/rack/shelf/bin.")
        zone, aisle, rack, shelf, bin_code = code.split("/")
        return cls(company_id, warehouse_id, zone, aisle, rack, shelf, bin_code)


@dataclass(frozen=True, slots=True)
class BinDimensions:
    """Fixed orientation: width, depth and height in metres, without implicit rotation."""

    width: Decimal
    depth: Decimal
    height: Decimal

    def __post_init__(self) -> None:
        for value in (self.width, self.depth, self.height):
            _amount(value, positive=True)

    @property
    def volume(self) -> Decimal:
        with localcontext() as context:
            context.prec = 80
            return self.width * self.depth * self.height

    def fits(self, outer: BinDimensions) -> bool:
        return (
            self.width <= outer.width and self.depth <= outer.depth and self.height <= outer.height
        )


@dataclass(frozen=True, slots=True)
class BinCapacity:
    dimensions: BinDimensions
    max_weight: Decimal
    max_units: int

    def __post_init__(self) -> None:
        if not isinstance(self.dimensions, BinDimensions):
            raise WmsLocationError("Bin dimensions are required.")
        _amount(self.max_weight, positive=True)
        if type(self.max_units) is not int or not 1 <= self.max_units <= 1000000:
            raise WmsLocationError("Capacity must contain 1 to 1000000 units.")


@dataclass(frozen=True, slots=True)
class PutawayLoad:
    company_id: UUID
    warehouse_id: UUID
    dimensions: BinDimensions
    unit_weight: Decimal
    units: int
    condition: StockCondition

    def __post_init__(self) -> None:
        _identity(self.company_id)
        _identity(self.warehouse_id)
        if not isinstance(self.dimensions, BinDimensions):
            raise WmsLocationError("Load dimensions are required.")
        _amount(self.unit_weight, positive=True)
        if type(self.units) is not int or not 1 <= self.units <= 1000000:
            raise WmsLocationError("Load must contain 1 to 1000000 units.")
        if not isinstance(self.condition, StockCondition):
            raise WmsLocationError("Unsupported stock condition.")


@dataclass(frozen=True, slots=True)
class PutawayPolicy:
    company_id: UUID
    warehouse_id: UUID
    allowed_zones: tuple[str, ...]

    def __post_init__(self) -> None:
        _identity(self.company_id)
        _identity(self.warehouse_id)
        if not isinstance(self.allowed_zones, tuple) or not self.allowed_zones:
            raise WmsLocationError("An immutable non-empty zone allowlist is required.")
        zones = tuple(_coordinate(value) for value in self.allowed_zones)
        if len(set(zones)) != len(zones):
            raise WmsLocationError("Duplicate zone in putaway policy.")
        object.__setattr__(self, "allowed_zones", zones)


@dataclass(frozen=True, slots=True)
class WarehouseBin:
    """Immutable occupancy projection, linked logically to a physical M5 location."""

    address: WarehouseAddress
    inventory_location_id: UUID
    capacity: BinCapacity
    storage_type: StorageType
    occupied_units: int = 0
    used_weight: Decimal = Decimal("0")
    used_volume: Decimal = Decimal("0")
    blocked: bool = False
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.address, WarehouseAddress) or not isinstance(
            self.capacity, BinCapacity
        ):
            raise WmsLocationError("A valid address and capacity are required.")
        _identity(self.inventory_location_id)
        if not isinstance(self.storage_type, StorageType):
            raise WmsLocationError("Unsupported storage type.")
        if type(self.blocked) is not bool or type(self.version) is not int or self.version < 1:
            raise WmsLocationError("Invalid block flag or version.")
        if type(self.occupied_units) is not int or self.occupied_units < 0:
            raise WmsLocationError("Occupied units must be a non-negative integer.")
        _amount(self.used_weight)
        # Volume derives from three six-place dimensions; retain all 18 places.
        if not isinstance(self.used_volume, Decimal) or not self.used_volume.is_finite():
            raise WmsLocationError("Used volume must be a finite Decimal.")
        if self.used_volume < 0:
            raise WmsLocationError("Used volume cannot be negative.")
        if (self.occupied_units == 0) != (self.used_weight == 0 and self.used_volume == 0):
            raise WmsLocationError("Empty occupancy must have zero weight and volume.")
        if self.occupied_units > 0 and (self.used_weight == 0 or self.used_volume == 0):
            raise WmsLocationError("Occupied bins require weight and volume evidence.")
        if (
            self.occupied_units > self.capacity.max_units
            or self.used_weight > self.capacity.max_weight
            or self.used_volume > self.capacity.dimensions.volume
        ):
            raise BinCapacityExceededError("Occupancy exceeds bin capacity.")

    @property
    def occupancy_status(self) -> OccupancyStatus:
        if self.blocked:
            return OccupancyStatus.BLOCKED
        if self.occupied_units == 0:
            return OccupancyStatus.EMPTY
        if (
            self.occupied_units == self.capacity.max_units
            or self.used_weight == self.capacity.max_weight
            or self.used_volume == self.capacity.dimensions.volume
        ):
            return OccupancyStatus.FULL
        return OccupancyStatus.PARTIAL

    def plan_putaway(self, load: PutawayLoad, policy: PutawayPolicy) -> WarehouseBin:
        if not isinstance(load, PutawayLoad) or not isinstance(policy, PutawayPolicy):
            raise WmsLocationError("Putaway requires a validated load and policy.")
        scope = self.address.company_id, self.address.warehouse_id
        if scope != (load.company_id, load.warehouse_id) or scope != (
            policy.company_id,
            policy.warehouse_id,
        ):
            raise WmsLocationError("Putaway crosses a company or warehouse boundary.")
        permitted = {
            StockCondition.AVAILABLE: {StorageType.PICKING, StorageType.RESERVE},
            StockCondition.DAMAGED: {StorageType.DAMAGED},
            StockCondition.QUARANTINE: {StorageType.QUARANTINE},
        }
        if (
            self.address.zone not in policy.allowed_zones
            or self.storage_type not in permitted[load.condition]
        ):
            raise PutawayZoneError("Zone or storage type does not permit this load.")
        if self.blocked:
            raise PutawayZoneError("Bin is blocked for putaway.")
        if not load.dimensions.fits(self.capacity.dimensions):
            raise BinCapacityExceededError("Load dimensions do not fit the bin.")
        with localcontext() as context:
            context.prec = 80
            return replace(
                self,
                occupied_units=self.occupied_units + load.units,
                used_weight=self.used_weight + load.unit_weight * load.units,
                used_volume=self.used_volume + load.dimensions.volume * load.units,
                version=self.version + 1,
            )


__all__ = [
    "BinCapacity",
    "BinCapacityExceededError",
    "BinDimensions",
    "OccupancyStatus",
    "PutawayLoad",
    "PutawayPolicy",
    "PutawayZoneError",
    "StockCondition",
    "StorageType",
    "WarehouseAddress",
    "WarehouseBin",
    "WmsLocationError",
]
