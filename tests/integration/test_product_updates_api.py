"""Versioned HTTP mutations, lost-update prevention and rollback of durable effects."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from erp.modules.product.application.permissions import PRODUCT_UPDATE
from erp.platform.audit import AuditEventModel
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.product_api_support import ApiFixture, product_api
from tests.integration.test_product_creation_api import allow_create, counts, creation_body

pytestmark = pytest.mark.integration


def create_for_update(api: ApiFixture) -> str:
    allow_create(api)
    response = api.client.post(
        "/api/v1/products",
        json=creation_body(api),
        headers={**api.headers, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    assert api.resolver.context is not None
    api.resolver.context = replace(
        api.resolver.context, permissions=api.resolver.context.permissions | {PRODUCT_UPDATE}
    )
    return str(response.headers["location"])


def test_patch_etag_audit_event_stale_version_and_noop() -> None:
    with product_api() as api:
        url = create_for_update(api)
        changed = api.client.patch(
            url, json={"name": "Nome alterado"}, headers={**api.headers, "If-Match": '"1"'}
        )
        assert changed.status_code == 200
        assert changed.headers["etag"] == '"2"'
        assert changed.json()["product"]["name"] == "Nome alterado"
        assert changed.json()["product"]["version"] == 2
        stale = api.client.patch(
            url, json={"uom": "CX"}, headers={**api.headers, "If-Match": '"1"'}
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
        unchanged = api.client.patch(
            url, json={"name": " Nome alterado "}, headers={**api.headers, "If-Match": '"2"'}
        )
        assert unchanged.status_code == 200
        assert unchanged.headers["etag"] == '"2"'
        assert unchanged.json()["event_id"] is None
        assert unchanged.json()["audit_event_id"] is None
        assert counts(api) == (1, 2, 2, 1)

        async def verify() -> None:
            async with api.data.database.session() as session:
                audit = await session.get(AuditEventModel, UUID(changed.json()["audit_event_id"]))
                outbox = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == UUID(changed.json()["event_id"])
                    )
                )
                assert audit is not None
                assert outbox is not None
                assert audit.before_snapshot is not None
                assert audit.after_snapshot is not None
                assert audit.before_snapshot["version"] == 1
                assert audit.after_snapshot["version"] == 2
                envelope = MessageEnvelope.model_validate(outbox.payload)
                assert envelope.message_type == "ProductUpdated"
                assert envelope.payload == {
                    "product_id": changed.json()["product"]["id"],
                    "changed_fields": ["name"],
                    "version": 2,
                }
                assert envelope.aggregate_version == 2

        assert api.client.portal is not None
        api.client.portal.call(verify)


@pytest.mark.parametrize(
    "etag",
    [None, "1", 'W/"1"', "*", '"0"', '"01"', '"-1"', '"1","2"', '"2147483648"', '"99999999999999"'],
)
def test_patch_requires_strong_bounded_etag(etag: str | None) -> None:
    with product_api() as api:
        url = create_for_update(api)
        headers = api.headers if etag is None else {**api.headers, "If-Match": etag}
        response = api.client.patch(url, json={"name": "Changed"}, headers=headers)
        assert response.status_code == (428 if etag is None else 400)
        assert response.json()["error"]["code"] == (
            "PRECONDITION_REQUIRED" if etag is None else "INVALID_IF_MATCH"
        )
        assert counts(api) == (1, 1, 1, 1)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": None},
        {"uom": None},
        {"name": " "},
        {"uom": "bad uom"},
        {"code": "CHANGED"},
        {"sku": "CHANGED"},
        {"lifecycle": "ATIVO"},
        {"version": 2},
        {"company_id": str(uuid4())},
    ],
)
def test_patch_rejects_invalid_fields_and_mass_assignment(body: dict[str, Any]) -> None:
    with product_api() as api:
        url = create_for_update(api)
        response = api.client.patch(url, json=body, headers={**api.headers, "If-Match": '"1"'})
        assert response.status_code == 422
        assert counts(api) == (1, 1, 1, 1)
        assert api.client.get(url, headers=api.headers).headers["etag"] == '"1"'


def test_update_denies_permission_foreign_context_and_missing_product() -> None:
    with product_api() as api:
        url = create_for_update(api)
        headers = {**api.headers, "If-Match": '"1"'}
        assert api.resolver.context is not None
        original = api.resolver.context
        api.resolver.context = replace(original, permissions=frozenset())
        assert api.client.patch(url, json={"uom": "CX"}, headers=headers).status_code == 403
        api.resolver.context = original
        foreign_url = url.replace(str(api.data.company_id), str(api.data.other_company_id))
        assert api.client.patch(foreign_url, json={"uom": "CX"}, headers=headers).status_code == 404
        missing_url = f"/api/v1/products/{uuid4()}?company_id={api.data.company_id}"
        assert api.client.patch(missing_url, json={"uom": "CX"}, headers=headers).status_code == 404
        assert counts(api) == (1, 1, 1, 1)


def test_concurrent_http_updates_have_one_winner_and_one_event() -> None:
    with product_api() as api:
        url = create_for_update(api)

        def update_name(number: int) -> int:
            return api.client.patch(
                url, json={"name": f"Name {number}"}, headers={**api.headers, "If-Match": '"1"'}
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(update_name, range(2)))
        assert sorted(statuses) == [200, 409]
        assert counts(api) == (1, 2, 2, 1)
        assert api.client.get(url, headers=api.headers).headers["etag"] == '"2"'


def test_update_rolls_back_version_and_audit_if_outbox_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Forced update failure")

    with product_api() as api:
        url = create_for_update(api)
        headers = {**api.headers, "If-Match": '"1"'}
        with monkeypatch.context() as patch:
            patch.setattr(OutboxService, "enqueue", fail)
            with pytest.raises(RuntimeError, match="Forced update failure"):
                api.client.patch(url, json={"uom": "CX"}, headers=headers)
        assert counts(api) == (1, 1, 1, 1)
        assert api.client.get(url, headers=api.headers).headers["etag"] == '"1"'
        assert api.client.patch(url, json={"uom": "CX"}, headers=headers).status_code == 200
