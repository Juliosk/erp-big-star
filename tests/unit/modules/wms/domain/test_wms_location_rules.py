"""Pure physical layout, capacity and tenant-safe putaway invariants."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.wms.domain.locations import (
    BinCapacity,
    BinCapacityExceededError,
    BinDimensions,
    OccupancyStatus,
    PutawayLoad,
    PutawayPolicy,
    PutawayZoneError,
    StockCondition,
    StorageType,
    WarehouseAddress,
    WarehouseBin,
    WmsLocationError,
)

D = Decimal


def bin_fixture() -> WarehouseBin:
    return WarehouseBin(
        WarehouseAddress(uuid4(), uuid4(), " a ", "01", "r1", "02", "003"),
        uuid4(),
        BinCapacity(BinDimensions(D("2"), D("2"), D("2")), D("10"), 10),
        StorageType.PICKING,
    )


def load_for(bin: WarehouseBin, **changes: object) -> PutawayLoad:
    load = PutawayLoad(
        bin.address.company_id,
        bin.address.warehouse_id,
        BinDimensions(D("1"), D("1"), D("1")),
        D("1"),
        1,
        StockCondition.AVAILABLE,
    )
    return cast(PutawayLoad, replace(cast(Any, load), **changes))


def policy_for(bin: WarehouseBin) -> PutawayPolicy:
    return PutawayPolicy(bin.address.company_id, bin.address.warehouse_id, ("a",))


def malformed(value: object, **changes: object) -> object:
    # Invalid transport-like inputs deliberately exercise constructor validation.
    return replace(cast(Any, value), **changes)


def test_address_normalization_roundtrip_scope_and_immutability() -> None:
    bin = bin_fixture()
    address = bin.address
    assert address.code == "A/01/R1/02/003"
    assert address.key == (address.company_id, address.warehouse_id, address.code)
    assert (
        WarehouseAddress.parse(
            company_id=address.company_id, warehouse_id=address.warehouse_id, code=address.code
        )
        == address
    )
    with pytest.raises(FrozenInstanceError):
        cast(Any, address).zone = "B"


@pytest.mark.parametrize("code", ["A/01/R1/02", "A/01/R1/02/003/extra", "A//R1/02/B", None])
def test_invalid_address_structure(code: str) -> None:
    address = bin_fixture().address
    with pytest.raises(WmsLocationError):
        WarehouseAddress.parse(
            company_id=address.company_id, warehouse_id=address.warehouse_id, code=code
        )


@pytest.mark.parametrize("coordinate", ["", " ", "A/B", "A-B", "Á", "A" * 17, None])
def test_invalid_coordinates(coordinate: object) -> None:
    with pytest.raises(WmsLocationError):
        malformed(bin_fixture().address, shelf=coordinate)


@pytest.mark.parametrize("field", ["company_id", "warehouse_id"])
@pytest.mark.parametrize("value", [UUID(int=0), None])
def test_invalid_scope_identity(field: str, value: object) -> None:
    with pytest.raises(WmsLocationError):
        malformed(bin_fixture().address, **{field: value})


@pytest.mark.parametrize(
    "measure", [D("0"), D("-1"), D("NaN"), D("Infinity"), D("1000000"), D("0.0000001"), 1.0]
)
def test_invalid_dimensions(measure: object) -> None:
    with pytest.raises(WmsLocationError):
        malformed(bin_fixture().capacity.dimensions, width=measure)


def test_projection_preserves_original_and_reports_occupancy() -> None:
    bin = bin_fixture()
    assert bin.occupancy_status is OccupancyStatus.EMPTY
    projected = bin.plan_putaway(load_for(bin), policy_for(bin))
    assert projected.occupancy_status is OccupancyStatus.PARTIAL
    assert projected.occupied_units == 1
    assert projected.used_weight == projected.used_volume == D("1")
    assert projected.version == 2
    assert bin.occupied_units == 0
    assert replace(projected, blocked=True).occupancy_status is OccupancyStatus.BLOCKED
    with pytest.raises(FrozenInstanceError):
        cast(Any, projected).occupied_units = 2


@pytest.mark.parametrize("constraint", ["units", "weight", "volume"])
def test_exact_capacity_is_full_and_one_extra_load_is_rejected(constraint: str) -> None:
    bin = bin_fixture()
    capacities = {
        "units": replace(bin.capacity, max_units=1),
        "weight": replace(bin.capacity, max_weight=D("1")),
        "volume": replace(bin.capacity, dimensions=BinDimensions(D("1"), D("1"), D("1"))),
    }
    bin = replace(bin, capacity=capacities[constraint])
    full = bin.plan_putaway(load_for(bin), policy_for(bin))
    assert full.occupancy_status is OccupancyStatus.FULL
    with pytest.raises(BinCapacityExceededError):
        full.plan_putaway(load_for(full), policy_for(full))


@pytest.mark.parametrize("axis", ["width", "depth", "height"])
def test_each_dimension_must_fit_without_implicit_rotation(axis: str) -> None:
    bin = bin_fixture()
    dimensions = replace(cast(Any, load_for(bin).dimensions), **{axis: D("3")})
    with pytest.raises(BinCapacityExceededError):
        bin.plan_putaway(load_for(bin, dimensions=dimensions), policy_for(bin))


@pytest.mark.parametrize("condition", list(StockCondition))
@pytest.mark.parametrize("storage", list(StorageType))
def test_zone_and_condition_matrix(condition: StockCondition, storage: StorageType) -> None:
    bin = replace(bin_fixture(), storage_type=storage)
    allowed = {
        StockCondition.AVAILABLE: {StorageType.PICKING, StorageType.RESERVE},
        StockCondition.DAMAGED: {StorageType.DAMAGED},
        StockCondition.QUARANTINE: {StorageType.QUARANTINE},
    }
    if storage in allowed[condition]:
        assert (
            bin.plan_putaway(load_for(bin, condition=condition), policy_for(bin)).occupied_units
            == 1
        )
    else:
        with pytest.raises(PutawayZoneError):
            bin.plan_putaway(load_for(bin, condition=condition), policy_for(bin))


def test_zone_allowlist_and_blocking_are_fail_closed() -> None:
    bin = bin_fixture()
    with pytest.raises(PutawayZoneError):
        bin.plan_putaway(load_for(bin), replace(policy_for(bin), allowed_zones=("B",)))
    with pytest.raises(PutawayZoneError):
        replace(bin, blocked=True).plan_putaway(load_for(bin), policy_for(bin))


@pytest.mark.parametrize("field", ["company_id", "warehouse_id"])
def test_load_and_policy_cannot_cross_company_or_warehouse(field: str) -> None:
    bin = bin_fixture()
    with pytest.raises(WmsLocationError):
        bin.plan_putaway(load_for(bin, **{field: uuid4()}), policy_for(bin))
    policy = replace(cast(Any, policy_for(bin)), **{field: uuid4()})
    with pytest.raises(WmsLocationError):
        bin.plan_putaway(load_for(bin), policy)


@pytest.mark.parametrize("zones", [(), [], ("A", "a"), ("!",)])
def test_policy_requires_immutable_unique_valid_zones(zones: object) -> None:
    with pytest.raises(WmsLocationError):
        malformed(policy_for(bin_fixture()), allowed_zones=zones)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dimensions", None),
        ("max_weight", D("0")),
        ("max_units", True),
        ("max_units", 0),
        ("max_units", 1000001),
    ],
)
def test_invalid_capacity(field: str, value: object) -> None:
    with pytest.raises(WmsLocationError):
        malformed(bin_fixture().capacity, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dimensions", None),
        ("unit_weight", D("0")),
        ("units", True),
        ("units", 0),
        ("units", 1000001),
        ("condition", "unknown"),
    ],
)
def test_invalid_load(field: str, value: object) -> None:
    with pytest.raises(WmsLocationError):
        load_for(bin_fixture(), **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("address", None),
        ("capacity", None),
        ("inventory_location_id", UUID(int=0)),
        ("storage_type", "unknown"),
        ("blocked", 1),
        ("version", 0),
        ("occupied_units", -1),
        ("occupied_units", True),
        ("used_volume", D("NaN")),
        ("used_volume", D("-1")),
        ("used_weight", D("1")),
    ],
)
def test_invalid_bin_construction(field: str, value: object) -> None:
    with pytest.raises(WmsLocationError):
        malformed(bin_fixture(), **{field: value})


def test_occupied_bin_requires_complete_weight_and_volume_evidence() -> None:
    bin = bin_fixture()
    for weight, volume in [(D("0"), D("0")), (D("1"), D("0")), (D("0"), D("1"))]:
        with pytest.raises(WmsLocationError):
            replace(bin, occupied_units=1, used_weight=weight, used_volume=volume)
    with pytest.raises(WmsLocationError):
        cast(Any, bin).plan_putaway(None, policy_for(bin))
    with pytest.raises(WmsLocationError):
        cast(Any, bin).plan_putaway(load_for(bin), None)


def test_tiny_volumes_are_exact_and_independent_of_ambient_precision() -> None:
    bin = bin_fixture()
    tiny = BinDimensions(D("0.000001"), D("0.000001"), D("0.000001"))
    with localcontext() as context:
        context.prec = 3
        projected = bin.plan_putaway(load_for(bin, dimensions=tiny, units=7), policy_for(bin))
    assert tiny.volume == D("0.000000000000000001")
    assert projected.used_volume == D("0.000000000000000007")
