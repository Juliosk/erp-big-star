"""Pure M5 inventory foundation rules."""

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.inventory.domain import (
    InventoryLot,
    InventoryLotStatus,
    InventoryPool,
    InventoryPoolKind,
    InventoryState,
    Quantity,
    Warehouse,
    WarehouseLocation,
)


def warehouse() -> Warehouse:
    return Warehouse.create(
        company_id=uuid4(),
        branch_id=uuid4(),
        code=" cd-sp ",
        name=" Centro de distribuição SP ",
    )


def test_warehouse_normalizes_identity_and_is_immutable() -> None:
    item = warehouse()

    assert item.code == "CD-SP"
    assert item.name == "Centro de distribuição SP"
    assert item.active is True
    assert item.version == 1
    with pytest.raises(FrozenInstanceError):
        item.name = "Mutable"  # type: ignore[misc]


def test_warehouse_rename_and_deactivate_increment_version_only_when_changed() -> None:
    item = warehouse()

    renamed = item.rename(" CD principal ")
    inactive = renamed.deactivate()

    assert renamed.name == "CD principal"
    assert renamed.version == 2
    assert item.rename(" Centro de distribuição SP ") is item
    assert inactive.active is False
    assert inactive.version == 3
    assert inactive.deactivate() is inactive


@pytest.mark.parametrize("code", ["A", "A B", "-BAD", "ábc", "A" * 51])
def test_warehouse_rejects_invalid_codes(code: str) -> None:
    with pytest.raises(ValueError, match="code"):
        Warehouse.create(company_id=uuid4(), branch_id=uuid4(), code=code, name="CD")


@pytest.mark.parametrize("value", ["", " ", "A" * 121])
def test_warehouse_rejects_invalid_names(value: str) -> None:
    with pytest.raises(ValueError, match="name"):
        Warehouse.create(company_id=uuid4(), branch_id=uuid4(), code="CD", name=value)


def test_location_belongs_to_one_company_warehouse_and_accepts_parent() -> None:
    parent_id = uuid4()
    location = WarehouseLocation.create(
        company_id=uuid4(),
        warehouse_id=uuid4(),
        parent_location_id=parent_id,
        code=" rua-01 ",
        name=" Rua 01 ",
    )

    assert location.code == "RUA-01"
    assert location.name == "Rua 01"
    assert location.parent_location_id == parent_id
    with pytest.raises(ValueError, match="own parent"):
        replace(location, parent_location_id=location.id)


def test_pool_uses_official_purposes_only() -> None:
    pool = InventoryPool.create(
        company_id=uuid4(),
        code=" b2b ",
        name=" Carteira B2B ",
        kind=InventoryPoolKind.B2B,
    )

    assert pool.code == "B2B"
    assert pool.name == "Carteira B2B"
    assert pool.kind is InventoryPoolKind.B2B
    with pytest.raises(ValueError, match="kind"):
        replace(pool, kind="WHOLESALE")  # type: ignore[arg-type]


def test_lot_tracks_product_scope_and_status_without_quantity() -> None:
    lot = InventoryLot.create(
        company_id=uuid4(),
        product_id=uuid4(),
        code=" lote/2026-01 ",
        expires_on=date(2027, 1, 31),
    )

    assert lot.code == "LOTE/2026-01"
    assert lot.status is InventoryLotStatus.OPEN
    assert lot.expires_on == date(2027, 1, 31)
    with pytest.raises(ValueError, match="status"):
        replace(lot, status="AVAILABLE")  # type: ignore[arg-type]


@pytest.mark.parametrize("state", list(InventoryState))
def test_inventory_states_match_official_foundation_set(state: InventoryState) -> None:
    assert state.value == state.name


@pytest.mark.parametrize("value", ["0", "1.123456", 5, Decimal("10.50")])
def test_quantity_accepts_non_negative_values_with_six_decimal_places(
    value: str | int | Decimal,
) -> None:
    assert Quantity.of(value).value >= Decimal("0")


@pytest.mark.parametrize("value", ["-0.01", Decimal("-1"), "1.1234567"])
def test_quantity_rejects_negative_or_over_precise_values(value: str | Decimal) -> None:
    with pytest.raises(ValueError, match="quantity"):
        Quantity.of(value)
