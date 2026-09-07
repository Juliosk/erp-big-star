"""Product invariants are exercised without infrastructure."""

from dataclasses import FrozenInstanceError, replace
from uuid import uuid4

import pytest

from erp.modules.product.domain import Product, ProductLifecycle, ProductType


def product() -> Product:
    return Product.create(
        company_id=uuid4(),
        code=" toy-01 ",
        sku=" bs.001 ",
        name=" Brinquedo ",
        product_type=ProductType.PA,
        uom=" un ",
    )


@pytest.mark.parametrize("kind", list(ProductType))
def test_creates_every_official_type_in_development(kind: ProductType) -> None:
    item = replace(product(), product_type=kind)
    assert (item.code, item.sku, item.name, item.uom) == ("TOY-01", "BS.001", "Brinquedo", "UN")
    assert item.lifecycle is ProductLifecycle.EM_DESENVOLVIMENTO
    assert item.version == 1


def with_identifier(item: Product, field: str, value: str) -> Product:
    if field == "code":
        return replace(item, code=value)
    if field == "sku":
        return replace(item, sku=value)
    return replace(item, uom=value)


@pytest.mark.parametrize("field", ["code", "sku", "uom"])
@pytest.mark.parametrize("value", ["", " ", "abc", "A B", "ÁBC", "-ABC", "A" * 65])
def test_rejects_noncanonical_identifiers(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=field):
        with_identifier(product(), field, value)


@pytest.mark.parametrize("name", ["", " ", " untrimmed", "untrimmed ", "A" * 201])
def test_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError, match="name"):
        replace(product(), name=name)


@pytest.mark.parametrize("version", [0, -1, True])
def test_rejects_invalid_versions(version: int) -> None:
    with pytest.raises(ValueError, match="version"):
        replace(product(), version=version)


def test_update_is_immutable_and_preserves_tenant_and_keys() -> None:
    original = product()
    changed = original.update_details(name=" Novo nome ", uom=" cx ")
    assert changed.name == "Novo nome"
    assert changed.uom == "CX"
    assert changed.version == 2
    assert replace(changed, name=original.name, uom=original.uom, version=1) == original
    assert original.update_details(name=" Brinquedo ", uom=" un ") is original
    with pytest.raises(FrozenInstanceError):
        original.name = "Mutable"  # type: ignore[misc]  # Deliberate runtime immutability probe.


def test_invalid_update_does_not_change_the_original() -> None:
    original = product()
    with pytest.raises(ValueError, match="name"):
        original.update_details(name="", uom="UN")
    assert original.version == 1


def test_rehydration_accepts_official_states_only() -> None:
    for state in ProductLifecycle:
        assert replace(product(), lifecycle=state).lifecycle is state
    with pytest.raises(ValueError, match="lifecycle"):
        replace(product(), lifecycle="ACTIVE")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="product_type"):
        replace(product(), product_type="UNKNOWN")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="UUID"):
        replace(product(), company_id=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="UUID"):
        replace(product(), id=None)  # type: ignore[arg-type]
