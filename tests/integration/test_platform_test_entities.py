"""End-to-end acceptance test for POST /api/v1/platform/test-entities."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from erp.apps.api.app import create_app
from erp.modules.platform_test.infrastructure import TestEntityModel as EntityModel
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.inbox import InboxEventModel
from erp.platform.outbox import OutboxEventModel


@pytest.mark.integration
def test_post_test_entities_persists_publishes_consumes_audits_and_replays() -> None:
    settings = get_settings()
    key = str(uuid4())
    correlation_id = str(uuid4())
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/platform/test-entities",
            json={"name": "Sprint 1 golden flow"},
            headers={"Idempotency-Key": key, "X-Correlation-ID": correlation_id},
        )
        replay = client.post(
            "/api/v1/platform/test-entities",
            json={"name": "Sprint 1 golden flow"},
            headers={"Idempotency-Key": key, "X-Correlation-ID": correlation_id},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "CONSUMED"
    assert payload["version"] == 2
    assert len(payload["audit_event_ids"]) == 2
    assert response.headers["Idempotency-Replayed"] == "false"
    assert replay.status_code == 201
    assert replay.json()["id"] == payload["id"]
    assert replay.json()["event_id"] == payload["event_id"]
    assert replay.json()["idempotency_replayed"] is True
    assert replay.headers["Idempotency-Replayed"] == "true"

    async def assert_durable_evidence() -> None:
        database = Database(settings)
        entity_id = UUID(payload["id"])
        event_id = UUID(payload["event_id"])
        try:
            async with database.session() as session:
                entity_count = await session.scalar(
                    select(func.count()).select_from(EntityModel).where(EntityModel.id == entity_id)
                )
                outbox = await session.scalar(
                    select(OutboxEventModel).where(OutboxEventModel.event_id == event_id)
                )
                inbox_count = await session.scalar(
                    select(func.count())
                    .select_from(InboxEventModel)
                    .where(InboxEventModel.event_id == event_id)
                )
                audit_count = await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(AuditEventModel.entity_id == entity_id)
                )

            assert entity_count == 1
            assert outbox is not None
            assert outbox.published_at is not None
            assert outbox.publish_attempts == 1
            assert inbox_count == 1
            assert audit_count == 2
        finally:
            await database.dispose()

    import asyncio

    asyncio.run(assert_durable_evidence())


@pytest.mark.integration
def test_post_test_entities_rejects_reused_key_with_different_payload() -> None:
    settings = get_settings()
    key = str(uuid4())
    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/v1/platform/test-entities",
            json={"name": "first payload"},
            headers={"Idempotency-Key": key},
        )
        conflict = client.post(
            "/api/v1/platform/test-entities",
            json={"name": "different payload"},
            headers={"Idempotency-Key": key},
        )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == ("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD")
