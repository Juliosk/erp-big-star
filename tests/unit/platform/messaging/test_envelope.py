"""Tests for the transport-neutral corporate message envelope."""

from datetime import UTC
from uuid import uuid4

import pytest
from pydantic import ValidationError

from erp.platform.messaging import MessageEnvelope, MessageKind


def build_envelope() -> MessageEnvelope:
    identity = uuid4()
    return MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type="TestEntityCreated",
        event_version=1,
        producer_module="platform",
        producer_domain="platform",
        aggregate_type="test_entity",
        aggregate_id=identity,
        aggregate_version=1,
        company_id=None,
        branch_id=None,
        correlation_id=identity,
        causation_id=None,
        request_id=identity,
        payload={"name": "atomic"},
    )


def test_new_envelope_is_versioned_immutable_and_utc() -> None:
    envelope = build_envelope()

    assert envelope.message_type == "TestEntityCreated"
    assert envelope.event_version == 1
    assert envelope.occurred_at.tzinfo is UTC
    assert envelope.model_dump(mode="json")["message_id"] == str(envelope.message_id)


def test_envelope_rejects_non_pascal_case_message_type() -> None:
    with pytest.raises(ValidationError):
        build_envelope().model_copy(update={"message_type": "test-entity-created"}).model_validate(
            {
                **build_envelope().model_dump(),
                "message_type": "test-entity-created",
            }
        )
