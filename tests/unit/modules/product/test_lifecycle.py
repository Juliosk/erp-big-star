"""Every pair of official lifecycle states has an explicit verdict."""

from dataclasses import replace
from uuid import uuid4

import pytest

from erp.modules.product.domain import Product, ProductLifecycle, ProductType


@pytest.mark.parametrize("source", list(ProductLifecycle))
@pytest.mark.parametrize("target", list(ProductLifecycle))
def test_only_strict_forward_transitions(
    source: ProductLifecycle, target: ProductLifecycle
) -> None:
    product = replace(
        Product.create(
            company_id=uuid4(), code="A", sku="A", name="Toy", product_type=ProductType.PA, uom="UN"
        ),
        lifecycle=source,
    )
    states = list(ProductLifecycle)
    if states.index(target) == states.index(source) + 1:
        changed = product.transition(target)
        assert changed.lifecycle == target
        assert changed.version == 2
    else:
        with pytest.raises(ValueError, match="not allowed"):
            product.transition(target)
