"""Pure route-aware picking, packing verification and expedition manifesto."""

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4


class WmsPickingPackingError(ValueError):
    code = "WMS_PICKING_PACKING_CONFLICT"


class PackingDivergenceError(WmsPickingPackingError):
    code = "WMS_PACKING_DIVERGENCE"


class PickingPackingWaveStatus(StrEnum):
    DRAFT = "DRAFT"
    PACKING = "PACKING"
    MANIFESTED = "MANIFESTED"


class PickingPackingItemStatus(StrEnum):
    OPEN = "OPEN"
    PICKED = "PICKED"
    PACKED = "PACKED"


@dataclass(frozen=True, slots=True)
class PickingPackingItem:
    id: UUID
    company_id: UUID
    wave_id: UUID
    sales_order_id: UUID
    shipment_id: UUID
    product_id: UUID
    warehouse_id: UUID
    bin_id: UUID
    barcode: str
    required_quantity: Decimal
    picked_quantity: Decimal
    packed_quantity: Decimal
    units: int
    unit_weight: Decimal
    unit_volume: Decimal
    route_address: str
    route_sequence: int
    status: PickingPackingItemStatus
    version: int
    lot_id: UUID | None = None
    pool_id: UUID | None = None

    def __post_init__(self) -> None:
        for identity in (
            self.id,
            self.company_id,
            self.wave_id,
            self.sales_order_id,
            self.shipment_id,
            self.product_id,
            self.warehouse_id,
            self.bin_id,
        ):
            _identity(identity)
        for optional_identity in (self.lot_id, self.pool_id):
            if optional_identity is not None:
                _identity(optional_identity)
        _canonical(self.barcode, maximum=64, separators="._-")
        if re.fullmatch(r"[A-Z0-9_]{1,16}(?:/[A-Z0-9_]{1,16}){4}", self.route_address) is None:
            raise WmsPickingPackingError("Invalid Cartesian picking address.")
        for amount in (
            self.required_quantity,
            self.picked_quantity,
            self.packed_quantity,
            self.unit_weight,
        ):
            _decimal(amount, max_places=6)
        _decimal(self.unit_volume, max_places=18)
        if self.required_quantity <= 0:
            raise WmsPickingPackingError("Required quantity must be positive.")
        if not 0 <= self.packed_quantity <= self.picked_quantity <= self.required_quantity:
            raise WmsPickingPackingError("Picking and packing quantities are inconsistent.")
        if type(self.units) is not int or self.units < 1:
            raise WmsPickingPackingError("Physical units must be positive.")
        if self.required_quantity != Decimal(self.units):
            raise WmsPickingPackingError("Physical units and stock quantity must match.")
        if self.unit_weight <= 0 or self.unit_volume <= 0:
            raise WmsPickingPackingError("Physical measures must be positive.")
        if type(self.route_sequence) is not int or self.route_sequence < 1:
            raise WmsPickingPackingError("Route sequence must be positive.")
        if not isinstance(self.status, PickingPackingItemStatus):
            raise WmsPickingPackingError("Invalid picking item status.")
        if type(self.version) is not int or self.version < 1:
            raise WmsPickingPackingError("Picking item version must be positive.")

    def mark_picked(self) -> PickingPackingItem:
        if self.status is not PickingPackingItemStatus.OPEN:
            raise WmsPickingPackingError("Only open items can be picked.")
        return replace(
            self,
            picked_quantity=self.required_quantity,
            status=PickingPackingItemStatus.PICKED,
            version=self.version + 1,
        )

    def scan(self, barcode: str, quantity: Decimal) -> PickingPackingItem:
        if self.status not in {
            PickingPackingItemStatus.PICKED,
            PickingPackingItemStatus.PACKED,
        }:
            raise PackingDivergenceError("The item has not been physically picked.")
        if barcode != self.barcode:
            raise PackingDivergenceError("Scanned barcode does not match the item.")
        _decimal(quantity, max_places=6)
        remaining = self.required_quantity - self.packed_quantity
        if quantity <= 0 or quantity > remaining:
            raise PackingDivergenceError("Scan quantity exceeds the unpacked balance.")
        packed = self.packed_quantity + quantity
        return replace(
            self,
            packed_quantity=packed,
            status=(
                PickingPackingItemStatus.PACKED
                if packed == self.required_quantity
                else PickingPackingItemStatus.PICKED
            ),
            version=self.version + 1,
        )


@dataclass(frozen=True, slots=True)
class PickingPackingWave:
    id: UUID
    company_id: UUID
    warehouse_id: UUID
    code: str
    status: PickingPackingWaveStatus
    version: int
    manifest_number: str | None = None
    manifested_at: datetime | None = None

    def __post_init__(self) -> None:
        for identity in (self.id, self.company_id, self.warehouse_id):
            _identity(identity)
        _canonical(self.code, maximum=64, separators="._-")
        if not isinstance(self.status, PickingPackingWaveStatus):
            raise WmsPickingPackingError("Invalid operational wave status.")
        if type(self.version) is not int or self.version < 1:
            raise WmsPickingPackingError("Wave version must be positive.")
        manifested = self.status is PickingPackingWaveStatus.MANIFESTED
        if manifested != (self.manifest_number is not None and self.manifested_at is not None):
            raise WmsPickingPackingError("Manifest state and evidence are inconsistent.")
        if self.manifest_number is not None:
            _canonical(self.manifest_number, maximum=64, separators="._-")
        if self.manifested_at is not None and self.manifested_at.tzinfo is None:
            raise WmsPickingPackingError("Manifest timestamp must be timezone-aware.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        warehouse_id: UUID,
        code: str,
        wave_id: UUID | None = None,
    ) -> PickingPackingWave:
        return cls(
            id=wave_id or uuid4(),
            company_id=company_id,
            warehouse_id=warehouse_id,
            code=code,
            status=PickingPackingWaveStatus.DRAFT,
            version=1,
        )

    def begin_packing(self, items: tuple[PickingPackingItem, ...]) -> PickingPackingWave:
        if self.status is not PickingPackingWaveStatus.DRAFT:
            raise WmsPickingPackingError("Only draft waves can execute picking.")
        _items_for_wave(self, items)
        if any(item.status is not PickingPackingItemStatus.PICKED for item in items):
            raise WmsPickingPackingError("Every route item must be picked first.")
        return replace(
            self,
            status=PickingPackingWaveStatus.PACKING,
            version=self.version + 1,
        )

    def generate_manifest(
        self,
        items: tuple[PickingPackingItem, ...],
        *,
        number: str,
        now: datetime | None = None,
    ) -> PickingPackingWave:
        if self.status is not PickingPackingWaveStatus.PACKING:
            raise WmsPickingPackingError("Only packing waves can be manifested.")
        _items_for_wave(self, items)
        if any(item.status is not PickingPackingItemStatus.PACKED for item in items):
            raise PackingDivergenceError("Every item must pass packing verification.")
        instant = now or datetime.now(UTC)
        return replace(
            self,
            status=PickingPackingWaveStatus.MANIFESTED,
            manifest_number=number,
            manifested_at=instant,
            version=self.version + 1,
        )


@dataclass(frozen=True, slots=True)
class ExpeditionManifest:
    number: str
    company_id: UUID
    warehouse_id: UUID
    wave_id: UUID
    order_ids: tuple[UUID, ...]
    shipment_ids: tuple[UUID, ...]
    item_count: int
    total_quantity: Decimal
    generated_at: datetime

    @classmethod
    def from_wave(
        cls, wave: PickingPackingWave, items: tuple[PickingPackingItem, ...]
    ) -> ExpeditionManifest:
        if wave.status is not PickingPackingWaveStatus.MANIFESTED:
            raise WmsPickingPackingError("A finalized wave is required.")
        _items_for_wave(wave, items)
        assert wave.manifest_number is not None
        assert wave.manifested_at is not None
        return cls(
            number=wave.manifest_number,
            company_id=wave.company_id,
            warehouse_id=wave.warehouse_id,
            wave_id=wave.id,
            order_ids=tuple(sorted({item.sales_order_id for item in items}, key=str)),
            shipment_ids=tuple(sorted({item.shipment_id for item in items}, key=str)),
            item_count=len(items),
            total_quantity=sum((item.packed_quantity for item in items), Decimal("0")),
            generated_at=wave.manifested_at,
        )


def _items_for_wave(wave: PickingPackingWave, items: tuple[PickingPackingItem, ...]) -> None:
    if not items or any(
        item.company_id != wave.company_id
        or item.wave_id != wave.id
        or item.warehouse_id != wave.warehouse_id
        for item in items
    ):
        raise WmsPickingPackingError("Wave items are missing or outside its scope.")


def _identity(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise WmsPickingPackingError("Identifiers must be non-zero UUIDs.")


def _canonical(value: str, *, maximum: int, separators: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise WmsPickingPackingError("Canonical text has an invalid length.")
    allowed = "".join(re.escape(value) for value in separators)
    if re.fullmatch(rf"[A-Z0-9][A-Z0-9{allowed}]*", value) is None:
        raise WmsPickingPackingError("Canonical text has invalid characters.")


def _decimal(value: Decimal, *, max_places: int) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise WmsPickingPackingError("Quantities and measures must be finite Decimals.")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -max_places:
        raise WmsPickingPackingError("Decimal precision exceeds the WMS contract.")


__all__ = [
    "ExpeditionManifest",
    "PackingDivergenceError",
    "PickingPackingItem",
    "PickingPackingItemStatus",
    "PickingPackingWave",
    "PickingPackingWaveStatus",
    "WmsPickingPackingError",
]
