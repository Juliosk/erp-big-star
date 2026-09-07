"""Unit tests for the technology-free temporary aggregate."""

import pytest

from erp.modules.platform_test.domain import TestEntity as Entity
from erp.modules.platform_test.domain import TestEntityStatus as EntityStatus


def test_test_entity_normalizes_name_and_increments_domain_version() -> None:
    created = Entity.create("  golden flow  ")
    consumed = created.mark_consumed()

    assert created.name == "golden flow"
    assert created.status is EntityStatus.CREATED
    assert created.version == 1
    assert consumed.status is EntityStatus.CONSUMED
    assert consumed.version == 2


def test_test_entity_rejects_blank_name() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        Entity.create("   ")
