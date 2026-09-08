"""Atomic HTTP creation, negative authorization and transaction fault injection."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from erp.modules.admin.domain import Scope, ScopeType
from erp.modules.product.application.permissions import PRODUCT_CREATE, PRODUCT_READ
from erp.modules.product.infrastructure import ProductModel
from erp.platform.audit import AuditEventModel, AuditService
from erp.platform.idempotency.models import IdempotencyRecordModel
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.product_api_support import ApiFixture, product_api

pytestmark = pytest.mark.integration


def creation_body(api: ApiFixture) -> dict[str, str]:
    return {
        "company_id": str(api.data.company_id),
        "code": "NEW",
        "sku": f"SKU-{uuid4().hex}",
        "name": "Brinquedo de teste",
        "product_type": "PA",
        "uom": "UN",
    }


def allow_create(api: ApiFixture) -> None:
    assert api.resolver.context is not None
    api.resolver.context = replace(
        api.resolver.context, permissions=frozenset({PRODUCT_CREATE, PRODUCT_READ})
    )


def counts(api: ApiFixture) -> tuple[int, int, int, int]:
    async def query() -> tuple[int, int, int, int]:
        async with api.data.database.session() as session:
            ids = select(ProductModel.id).where(ProductModel.company_id == api.data.company_id)
            products = await session.scalar(
                select(func.count())
                .select_from(ProductModel)
                .where(ProductModel.company_id == api.data.company_id)
            )
            audit = await session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(
                    AuditEventModel.company_id == api.data.company_id,
                    AuditEventModel.module == "product",
                )
            )
            outbox = await session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.aggregate_id.in_(ids))
            )
            idem = await session.scalar(
                select(func.count())
                .select_from(IdempotencyRecordModel)
                .where(
                    IdempotencyRecordModel.scope
                    == f"product:{api.data.company_id}:{api.data.actor_id}"
                )
            )
            return products or 0, audit or 0, outbox or 0, idem or 0

    assert api.client.portal is not None
    return cast(tuple[int, int, int, int], api.client.portal.call(query))


def test_create_replay_conflict_and_correlation_are_atomic() -> None:
    with product_api() as api:
        allow_create(api)
        body = creation_body(api)
        correlation_id, request_id = uuid4(), uuid4()
        headers = {
            **api.headers,
            "Idempotency-Key": str(uuid4()),
            "X-Correlation-ID": str(correlation_id),
            "X-Request-ID": str(request_id),
        }
        first = api.client.post("/api/v1/products", json=body, headers=headers)
        replay = api.client.post("/api/v1/products", json=body, headers=headers)
        assert first.status_code == replay.status_code == 201
        assert first.headers["etag"] == '"1"'
        assert replay.headers["idempotency-replayed"] == "true"
        assert first.json()["product"] == replay.json()["product"]
        assert first.json()["event_id"] == replay.json()["event_id"]
        assert api.client.get(first.headers["location"], headers=api.headers).status_code == 200
        conflict = api.client.post(
            "/api/v1/products", json={**body, "name": "Changed payload"}, headers=headers
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"
        assert counts(api) == (1, 1, 1, 1)

        async def verify() -> None:
            async with api.data.database.session() as session:
                outbox = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == UUID(first.json()["event_id"])
                    )
                )
                audit = await session.get(AuditEventModel, UUID(first.json()["audit_event_id"]))
                assert outbox is not None
                assert audit is not None
                envelope = MessageEnvelope.model_validate(outbox.payload)
                assert envelope.message_type == "ProductCreated"
                assert envelope.payload == {
                    "product_id": first.json()["product"]["id"],
                    "sku": body["sku"].upper(),
                    "product_type": "PA",
                }
                assert envelope.company_id == api.data.company_id
                assert envelope.aggregate_version == 1
                assert envelope.correlation_id == audit.correlation_id == correlation_id
                assert envelope.request_id == audit.request_id == request_id
                assert audit.actor_user_id == api.data.actor_id
                assert outbox.published_at is None
                assert audit.before_snapshot is None

        assert api.client.portal is not None
        api.client.portal.call(verify)
        assert api.resolver.context is not None
        api.resolver.context = replace(api.resolver.context, permissions=frozenset())
        assert api.client.post("/api/v1/products", json=body, headers=headers).status_code == 403


def test_creation_requires_permission_scope_and_idempotency_key() -> None:
    with product_api() as api:
        body = creation_body(api)
        headers = {**api.headers, "Idempotency-Key": str(uuid4())}
        assert api.client.post("/api/v1/products", json=body, headers=headers).status_code == 403
        allow_create(api)
        assert (
            api.client.post("/api/v1/products", json=body, headers=api.headers).status_code == 422
        )
        assert (
            api.client.post(
                "/api/v1/products",
                json={**body, "company_id": str(api.data.other_company_id)},
                headers=headers,
            ).status_code
            == 404
        )
        assert counts(api) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "changes",
    [
        {"code": "bad code"},
        {"name": " "},
        {"lifecycle": "ATIVO"},
        {"version": 5},
        {"company_id": None},
    ],
)
def test_creation_rejects_invalid_or_mass_assigned_fields(changes: dict[str, Any]) -> None:
    with product_api() as api:
        allow_create(api)
        response = api.client.post(
            "/api/v1/products",
            json={**creation_body(api), **changes},
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 422
        assert counts(api) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    ("component", "method"), [(AuditService, "record"), (OutboxService, "enqueue")]
)
def test_failed_effect_rolls_back_product_audit_outbox_and_key(
    monkeypatch: pytest.MonkeyPatch,
    component: type[Any],
    method: str,
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Forced transaction failure")

    with product_api() as api:
        allow_create(api)
        body = creation_body(api)
        headers = {**api.headers, "Idempotency-Key": str(uuid4())}
        with monkeypatch.context() as patch:
            patch.setattr(component, method, fail)
            with pytest.raises(RuntimeError, match="Forced transaction failure"):
                api.client.post("/api/v1/products", json=body, headers=headers)
        assert counts(api) == (0, 0, 0, 0)
        assert api.client.post("/api/v1/products", json=body, headers=headers).status_code == 201
        assert counts(api) == (1, 1, 1, 1)


def test_concurrent_duplicate_requests_create_exactly_one_product() -> None:
    with product_api() as api:
        allow_create(api)
        body = creation_body(api)
        headers = {**api.headers, "Idempotency-Key": str(uuid4())}

        def request(_: int) -> tuple[int, bool]:
            response = api.client.post("/api/v1/products", json=body, headers=headers)
            return response.status_code, response.json()["idempotency_replayed"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request, range(2)))
        assert sorted(results) == [(201, False), (201, True)]
        assert counts(api) == (1, 1, 1, 1)


def test_same_key_is_isolated_between_companies_and_duplicates_stay_generic() -> None:
    with product_api() as api:
        allow_create(api)
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            scopes=frozenset(
                {
                    Scope(ScopeType.COMPANY, api.data.company_id),
                    Scope(ScopeType.COMPANY, api.data.other_company_id),
                }
            ),
        )
        body = creation_body(api)
        headers = {**api.headers, "Idempotency-Key": str(uuid4())}
        assert api.client.post("/api/v1/products", json=body, headers=headers).status_code == 201
        foreign = {**body, "company_id": str(api.data.other_company_id)}
        conflict = api.client.post("/api/v1/products", json=foreign, headers=headers)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "PRODUCT_IDENTIFIER_CONFLICT"
        assert (
            api.client.post(
                "/api/v1/products", json={**foreign, "sku": f"OTHER-{uuid4().hex}"}, headers=headers
            ).status_code
            == 201
        )
