"""Approved lifecycle sequence, RBAC, retries and durable event contracts."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select

from erp.modules.product.application.permissions import PRODUCT_ACTIVATE, PRODUCT_DISCONTINUE
from erp.platform.outbox import OutboxEventModel
from tests.integration.product_api_support import product_api
from tests.integration.test_product_updates_api import create_for_update

pytestmark = pytest.mark.integration


def test_lifecycle_sequence_permissions_replay_and_events() -> None:
    with product_api() as api:
        url = create_for_update(api)
        path, query = url.split("?")
        assert api.resolver.context is not None

        def call(action: str, version: int, key: str | None = None):  # type: ignore[no-untyped-def]
            return api.client.post(
                f"{path}/{action}?{query}",
                headers={
                    **api.headers,
                    "If-Match": f'"{version}"',
                    "Idempotency-Key": key or str(uuid4()),
                },
            )

        assert call("submit-for-homologation", 1).status_code == 403
        api.resolver.context = replace(
            api.resolver.context, permissions=api.resolver.context.permissions | {PRODUCT_ACTIVATE}
        )
        assert call("activate", 1).json()["error"]["code"] == "INVALID_LIFECYCLE_TRANSITION"
        key = str(uuid4())
        submitted = call("submit-for-homologation", 1, key)
        assert submitted.status_code == 200
        assert submitted.headers["etag"] == '"2"'
        assert call("submit-for-homologation", 1, key).headers["idempotency-replayed"] == "true"
        assert call("activate", 1).json()["error"]["code"] == "VERSION_CONFLICT"
        assert call("activate", 2).headers["etag"] == '"3"'
        assert call("discontinue", 3).status_code == 403
        api.resolver.context = replace(
            api.resolver.context,
            permissions=api.resolver.context.permissions | {PRODUCT_DISCONTINUE},
        )
        assert call("discontinue", 3).headers["etag"] == '"4"'
        assert call("activate", 4).status_code == 409

        async def verify() -> None:
            async with api.data.database.session() as session:
                events = (
                    await session.scalars(
                        select(OutboxEventModel)
                        .where(OutboxEventModel.aggregate_id == submitted.json()["product"]["id"])
                        .order_by(OutboxEventModel.occurred_at)
                    )
                ).all()
                assert [event.event_type for event in events] == [
                    "ProductCreated",
                    "ProductUpdated",
                    "ProductActivated",
                    "ProductDiscontinued",
                ]

        assert api.client.portal is not None
        api.client.portal.call(verify)
