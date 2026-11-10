"""Pure proofs for route picking, packing scans and manifests."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from erp.modules.wms.domain import (
    BinCapacity,
    BinDimensions,
    BinPickError,
    ExpeditionManifest,
    PackingDivergenceError,
    PickingPackingItem,
    PickingPackingItemStatus,
    PickingPackingWave,
    PickingPackingWaveStatus,
    StorageType,
    WarehouseAddress,
    WarehouseBin,
    WmsPickingPackingError,
)

D = Decimal


def _wave() -> PickingPackingWave:
    return PickingPackingWave.create(company_id=uuid4(), warehouse_id=uuid4(), code="WAVE214")


def _item(wave: PickingPackingWave, *, units: int = 2) -> PickingPackingItem:
    return PickingPackingItem(
        id=uuid4(),
        company_id=wave.company_id,
        wave_id=wave.id,
        sales_order_id=uuid4(),
        shipment_id=uuid4(),
        product_id=uuid4(),
        warehouse_id=wave.warehouse_id,
        bin_id=uuid4(),
        barcode="7890000000214",
        required_quantity=D(units),
        picked_quantity=D("0"),
        packed_quantity=D("0"),
        units=units,
        unit_weight=D("2"),
        unit_volume=D("1"),
        route_address="PICK/A01/R01/S01/B01",
        route_sequence=1,
        status=PickingPackingItemStatus.OPEN,
        version=1,
    )


def _bin(*, units: int = 3, blocked: bool = False) -> WarehouseBin:
    return WarehouseBin(
        WarehouseAddress(uuid4(), uuid4(), "PICK", "A01", "R01", "S01", "B01"),
        uuid4(),
        BinCapacity(BinDimensions(D("2"), D("2"), D("2")), D("20"), 10),
        StorageType.PICKING,
        occupied_units=units,
        used_weight=D(units * 2),
        used_volume=D(units),
        blocked=blocked,
    )


def test_complete_picking_packing_and_manifest_lifecycle_is_immutable() -> None:
    wave = _wave()
    open_item = _item(wave)
    picked = open_item.mark_picked()
    packing = wave.begin_packing((picked,))
    partial = picked.scan(open_item.barcode, D("1"))
    packed = partial.scan(open_item.barcode, D("1"))
    now = datetime(2026, 11, 10, 18, 0, tzinfo=UTC)
    manifested = packing.generate_manifest((packed,), number="MNF-214", now=now)
    manifest = ExpeditionManifest.from_wave(manifested, (packed,))

    assert open_item.status is PickingPackingItemStatus.OPEN
    assert picked.status is PickingPackingItemStatus.PICKED
    assert partial.status is PickingPackingItemStatus.PICKED
    assert packed.status is PickingPackingItemStatus.PACKED
    assert packed.version == 4
    assert manifested.status is PickingPackingWaveStatus.MANIFESTED
    assert manifested.version == 3
    assert manifest.total_quantity == D("2")
    assert manifest.generated_at == now
    with pytest.raises(FrozenInstanceError):
        manifested.version = 4  # type: ignore[misc]


def test_packing_divergences_and_wave_guards_fail_closed() -> None:
    wave = _wave()
    open_item = _item(wave)
    with pytest.raises(PackingDivergenceError, match="not been physically picked"):
        open_item.scan(open_item.barcode, D("1"))
    picked = open_item.mark_picked()
    with pytest.raises(PackingDivergenceError, match="does not match"):
        picked.scan("7899999999999", D("1"))
    with pytest.raises(PackingDivergenceError, match="exceeds"):
        picked.scan(open_item.barcode, D("3"))
    with pytest.raises(PackingDivergenceError, match="exceeds"):
        picked.scan(open_item.barcode, D("0"))
    with pytest.raises(WmsPickingPackingError, match="Only open"):
        picked.mark_picked()
    with pytest.raises(WmsPickingPackingError, match="must be picked"):
        wave.begin_packing((open_item,))
    packing = wave.begin_packing((picked,))
    with pytest.raises(PackingDivergenceError, match="must pass"):
        packing.generate_manifest((picked,), number="MNF-214")
    with pytest.raises(WmsPickingPackingError, match="Only packing"):
        wave.generate_manifest((picked,), number="MNF-214")
    with pytest.raises(WmsPickingPackingError, match="Only draft"):
        packing.begin_packing((picked,))
    with pytest.raises(WmsPickingPackingError, match="finalized"):
        ExpeditionManifest.from_wave(wave, (open_item,))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", UUID(int=0)),
        ("company_id", "invalid"),
        ("barcode", ""),
        ("barcode", "lowercase"),
        ("route_address", "INVALID"),
        ("required_quantity", D("0")),
        ("required_quantity", D("1")),
        ("packed_quantity", D("3")),
        ("units", 0),
        ("unit_weight", D("0")),
        ("unit_volume", D("NaN")),
        ("unit_volume", D("0.0000000000000000001")),
        ("route_sequence", 0),
        ("status", "OPEN"),
        ("version", 0),
    ],
)
def test_invalid_picking_item_snapshots_are_rejected(field: str, value: object) -> None:
    with pytest.raises(WmsPickingPackingError):
        replace(_item(_wave()), **{field: value})  # type: ignore[arg-type]


def test_wave_snapshot_and_scope_invariants_are_enforced() -> None:
    wave = _wave()
    item = _item(wave).mark_picked()
    with pytest.raises(WmsPickingPackingError, match="evidence"):
        replace(wave, status=PickingPackingWaveStatus.MANIFESTED)
    with pytest.raises(WmsPickingPackingError, match="Invalid operational"):
        replace(wave, status="DRAFT")  # type: ignore[arg-type]
    with pytest.raises(WmsPickingPackingError, match="version"):
        replace(wave, version=0)
    with pytest.raises(WmsPickingPackingError, match="timezone-aware"):
        replace(
            wave,
            status=PickingPackingWaveStatus.MANIFESTED,
            manifest_number="MNF-214",
            manifested_at=datetime(2026, 11, 10),  # noqa: DTZ001
        )
    with pytest.raises(WmsPickingPackingError, match="outside"):
        wave.begin_packing((replace(item, company_id=uuid4()),))
    with pytest.raises(WmsPickingPackingError, match="missing"):
        wave.begin_packing(())
    assert replace(item, lot_id=uuid4()).lot_id is not None


def test_manifest_can_generate_its_own_aware_timestamp() -> None:
    wave = _wave()
    picked = _item(wave).mark_picked()
    packing = wave.begin_packing((picked,))
    packed = picked.scan("7890000000214", D("2"))
    manifested = packing.generate_manifest((packed,), number="MNF-AUTO")
    assert manifested.manifested_at is not None
    assert manifested.manifested_at.tzinfo is not None


def test_bin_pick_updates_partial_and_empty_occupancy() -> None:
    original = _bin()
    partial = original.plan_pick(units=1, unit_weight=D("2"), unit_volume=D("1"))
    empty = partial.plan_pick(units=2, unit_weight=D("2"), unit_volume=D("1"))
    assert (partial.occupied_units, partial.used_weight, partial.used_volume) == (
        2,
        D("4"),
        D("2"),
    )
    assert (empty.occupied_units, empty.used_weight, empty.used_volume) == (
        0,
        D("0"),
        D("0"),
    )
    assert empty.version == 3


@pytest.mark.parametrize(
    ("bin_value", "units", "weight", "volume"),
    [
        (_bin(), 0, D("2"), D("1")),
        (_bin(), 1, D("0"), D("1")),
        (_bin(blocked=True), 1, D("2"), D("1")),
        (_bin(), 4, D("2"), D("1")),
    ],
)
def test_bin_pick_rejects_invalid_or_unavailable_loads(
    bin_value: WarehouseBin,
    units: int,
    weight: Decimal,
    volume: Decimal,
) -> None:
    with pytest.raises(BinPickError):
        bin_value.plan_pick(units=units, unit_weight=weight, unit_volume=volume)


__all__: list[str] = []
