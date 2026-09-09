"""M14 customer API covers RBAC, tenant scope, idempotency, audit and outbox."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from erp.modules.admin.domain import Scope, ScopeType
from erp.modules.customer.application.permissions import CUSTOMER_CREATE, CUSTOMER_READ
from erp.modules.customer.infrastructure import CustomerModel
from erp.platform.audit import AuditEventModel, AuditService
from erp.platform.idempotency.models import IdempotencyRecordModel
from erp.platform.idempotency.service import IdempotencyDecision, IdempotencyService
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.customer_api_support import CustomerApiFixture, customer_api

pytestmark = pytest.mark.integration


def creation_body(api: CustomerApiFixture, *, cpf: str = "529.982.247-25") -> dict[str, str]:
    return {
        "company_id": str(api.data.company_id),
        "customer_type": "INDIVIDUAL",
        "identity_type": "CPF",
        "identity_value": cpf,
        "legal_name": "Maria Souza",
        "trade_name": "Maria",
    }


def allow_create(api: CustomerApiFixture) -> None:
    assert api.resolver.context is not None
    api.resolver.context = replace(
        api.resolver.context, permissions=frozenset({CUSTOMER_CREATE, CUSTOMER_READ})
    )


def counts(api: CustomerApiFixture) -> tuple[int, int, int, int]:
    async def query() -> tuple[int, int, int, int]:
        async with api.data.database.session() as session:
            ids = select(CustomerModel.id).where(CustomerModel.company_id == api.data.company_id)
            customers = await session.scalar(
                select(func.count())
                .select_from(CustomerModel)
                .where(CustomerModel.company_id == api.data.company_id)
            )
            audit = await session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(
                    AuditEventModel.company_id == api.data.company_id,
                    AuditEventModel.module == "crm",
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
                    == f"customer:{api.data.company_id}:{api.data.actor_id}"
                )
            )
            return customers or 0, audit or 0, outbox or 0, idem or 0

    assert api.client.portal is not None
    return cast(tuple[int, int, int, int], api.client.portal.call(query))


def test_create_list_get_replay_and_effects_are_atomic() -> None:
    with customer_api() as api:
        allow_create(api)
        assert api.client.get(api.url, headers=api.headers).json()["data"] == []
        body = creation_body(api)
        correlation_id, request_id = uuid4(), uuid4()
        headers = {
            **api.headers,
            "Idempotency-Key": str(uuid4()),
            "X-Correlation-ID": str(correlation_id),
            "X-Request-ID": str(request_id),
        }

        first = api.client.post("/api/v1/customers", json=body, headers=headers)
        replay = api.client.post("/api/v1/customers", json=body, headers=headers)

        assert first.status_code == replay.status_code == 201
        assert first.headers["etag"] == '"1"'
        assert replay.headers["idempotency-replayed"] == "true"
        assert first.json()["customer"] == replay.json()["customer"]
        assert first.json()["customer"]["identity_value"] == "52998224725"
        assert first.json()["customer"]["identity_ref"] == "CPF:***4725"
        assert api.client.get(first.headers["location"], headers=api.headers).status_code == 200
        listed = api.client.get(
            f"{api.url}&status=ACTIVE&customer_type=INDIVIDUAL", headers=api.headers
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["data"]] == [first.json()["customer"]["id"]]
        conflict = api.client.post(
            "/api/v1/customers", json={**body, "legal_name": "Changed"}, headers=headers
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
                assert envelope.message_type == "CustomerCreated"
                assert envelope.payload == {
                    "customer_id": first.json()["customer"]["id"],
                    "type": "INDIVIDUAL",
                    "identity_ref": "CPF:***4725",
                }
                assert envelope.company_id == api.data.company_id
                assert envelope.aggregate_version == 1
                assert envelope.correlation_id == audit.correlation_id == correlation_id
                assert envelope.request_id == audit.request_id == request_id
                assert audit.actor_user_id == api.data.actor_id
                assert audit.before_snapshot is None
                assert audit.after_snapshot is not None
                assert "identity_value" not in audit.after_snapshot
                assert audit.after_snapshot["identity_ref"] == "CPF:***4725"
                assert outbox.published_at is None

        assert api.client.portal is not None
        api.client.portal.call(verify)


def test_creation_requires_permission_scope_and_idempotency_key() -> None:
    with customer_api() as api:
        body = creation_body(api)
        headers = {**api.headers, "Idempotency-Key": str(uuid4())}
        assert api.client.post("/api/v1/customers", json=body, headers=headers).status_code == 403
        allow_create(api)
        assert (
            api.client.post("/api/v1/customers", json=body, headers=api.headers).status_code == 422
        )
        assert (
            api.client.post(
                "/api/v1/customers",
                json={**body, "company_id": str(api.data.other_company_id)},
                headers=headers,
            ).status_code
            == 404
        )
        assert counts(api) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "changes",
    [
        {"identity_value": "111.111.111-11"},
        {"customer_type": "COMPANY"},
        {"trade_name": " "},
        {"status": "BLOCKED"},
        {"version": 5},
        {"company_id": None},
    ],
)
def test_creation_rejects_invalid_or_mass_assigned_fields(changes: dict[str, Any]) -> None:
    with customer_api() as api:
        allow_create(api)
        response = api.client.post(
            "/api/v1/customers",
            json={**creation_body(api), **changes},
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 422
        assert counts(api) == (0, 0, 0, 0)


def test_duplicate_identity_error_is_scoped_and_generic() -> None:
    with customer_api() as api:
        allow_create(api)
        body = creation_body(api)
        headers = {**api.headers, "Idempotency-Key": str(uuid4())}
        assert api.client.post("/api/v1/customers", json=body, headers=headers).status_code == 201
        duplicate = api.client.post(
            "/api/v1/customers",
            json={**body, "legal_name": "Outra Maria"},
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "CUSTOMER_DUPLICATE_EXACT_MATCH"
        assert "52998224725" not in duplicate.text
        assert counts(api) == (1, 1, 1, 1)

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
        foreign = {**body, "company_id": str(api.data.other_company_id)}
        assert (
            api.client.post(
                "/api/v1/customers",
                json=foreign,
                headers={**api.headers, "Idempotency-Key": str(uuid4())},
            ).status_code
            == 201
        )


@pytest.mark.parametrize(
    ("component", "method"), [(AuditService, "record"), (OutboxService, "enqueue")]
)
def test_failed_effect_rolls_back_customer_audit_outbox_and_key(
    monkeypatch: pytest.MonkeyPatch,
    component: type[Any],
    method: str,
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Forced customer transaction failure")

    with customer_api() as api:
        allow_create(api)
        body = creation_body(api)
        headers = {**api.headers, "Idempotency-Key": str(uuid4())}
        with monkeypatch.context() as patch:
            patch.setattr(component, method, fail)
            with pytest.raises(RuntimeError, match="Forced customer transaction failure"):
                api.client.post("/api/v1/customers", json=body, headers=headers)
        assert counts(api) == (0, 0, 0, 0)
        assert api.client.post("/api/v1/customers", json=body, headers=headers).status_code == 201
        assert counts(api) == (1, 1, 1, 1)


def test_concurrent_duplicate_requests_create_exactly_one_customer() -> None:
    with customer_api() as api:
        allow_create(api)
        body = creation_body(api)
        headers = {**api.headers, "Idempotency-Key": str(uuid4())}

        def request(_: int) -> tuple[int, bool]:
            response = api.client.post("/api/v1/customers", json=body, headers=headers)
            return response.status_code, response.json()["idempotency_replayed"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request, range(2)))
        assert sorted(results) == [(201, False), (201, True)]
        assert counts(api) == (1, 1, 1, 1)


def test_corrupt_replay_does_not_execute_a_new_command(monkeypatch: pytest.MonkeyPatch) -> None:
    async def corrupt_replay(*args: Any, **kwargs: Any) -> IdempotencyDecision:
        return IdempotencyDecision(record_id=uuid4(), replayed=True)

    with customer_api() as api:
        allow_create(api)
        monkeypatch.setattr(IdempotencyService, "begin", corrupt_replay)
        with pytest.raises(RuntimeError, match="no response body"):
            api.client.post(
                "/api/v1/customers",
                json=creation_body(api),
                headers={**api.headers, "Idempotency-Key": str(uuid4())},
            )
        assert counts(api) == (0, 0, 0, 0)
