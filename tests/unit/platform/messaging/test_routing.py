"""Tests for mandatory RabbitMQ routing conventions."""

import pytest

from erp.platform.messaging import build_routing_key
from erp.platform.messaging.routing import action_from_message_type


def test_build_routing_key_uses_corporate_convention() -> None:
    assert (
        build_routing_key(domain="platform", aggregate="test-entity", action="created", version=1)
        == "platform.test-entity.created.v1"
    )


@pytest.mark.parametrize("segment", ["Platform", "test.entity", "created!"])
def test_build_routing_key_rejects_invalid_segments(segment: str) -> None:
    with pytest.raises(ValueError, match="lowercase"):
        build_routing_key(domain=segment, aggregate="entity", action="created", version=1)


def test_action_is_derived_from_pascal_case_type() -> None:
    assert action_from_message_type("TestEntityCreated") == "created"
