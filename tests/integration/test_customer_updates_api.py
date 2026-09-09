"""M14 PATCH API enforces ETags, status transitions and CustomerUpdated effects."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from erp.modules.customer.application.permissions import (
    CUSTOMER_CREATE,
    CUSTOMER_READ,
    CUSTOMER_UPDATE,
)
from erp.modules.customer.infrastructure import CustomerModel
from erp.platform.audit import AuditEventModel, AuditService
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.customer_api_support import CustomerApiFixture, customer_api
from tests.integration.test_customer_creation_api import allow_create, creation_body

pytestmark = pytest.mark.integration


def allow_update(api: CustomerApiFixture) -> None:
    assert api.resolver.context is not None
    api.resolver.context = replace(
        api.resolver.context,
        permissions=frozenset({CUSTOMER_CREATE, CUSTOMER_READ, CUSTOMER_UPDATE}),
    )


def create_customer(api: CustomerApiFixture) -> dict[str, Any]:
    allow_create(api)
    response = api.client.post(
        "/api/v1/customers",
        json=creation_body(api),
        headers={**api.headers, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    allow_update(api)
    return cast(dict[str, Any], response.json()["customer"])


def update_counts(api: CustomerApiFixture) -> tuple[int, int]:
    async def query() -> tuple[int, int]:
        async with api.data.database.session() as session:
            customers = select(CustomerModel.id).where(
                CustomerModel.company_id == api.data.company_id
            )
            audit = await session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(
                    AuditEventModel.company_id == api.data.company_id,
                    AuditEventModel.module == "crm",
                    AuditEventModel.operation == "CustomerUpdated",
                )
            )
            outbox = await session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(
                    OutboxEventModel.aggregate_id.in_(customers),
                    OutboxEventModel.event_type == "CustomerUpdated",
                )
            )
            return audit or 0, outbox or 0

    assert api.client.portal is not None
    return cast(tuple[int, int], api.client.portal.call(query))


def test_patch_updates_customer_and_records_customer_updated() -> None:
    with customer_api() as api:
        customer = create_customer(api)
        correlation_id, request_id = uuid4(), uuid4()
        response = api.client.patch(
            f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
            json={"legal_name": "Maria Souza Atualizada", "trade_name": None, "status": "BLOCKED"},
            headers={
                **api.headers,
                "If-Match": '"1"',
                "X-Correlation-ID": str(correlation_id),
                "X-Request-ID": str(request_id),
            },
        )

        assert response.status_code == 200
        assert response.headers["etag"] == '"3"'
        body = response.json()
        assert body["event_id"] is not None
        assert body["audit_event_id"] is not None
        assert body["customer"]["legal_name"] == "Maria Souza Atualizada"
        assert body["customer"]["trade_name"] is None
        assert body["customer"]["status"] == "BLOCKED"
        assert update_counts(api) == (1, 1)

        async def verify() -> None:
            async with api.data.database.session() as session:
                outbox = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == UUID(body["event_id"])
                    )
                )
                audit = await session.get(AuditEventModel, UUID(body["audit_event_id"]))
                assert outbox is not None
                assert audit is not None
                envelope = MessageEnvelope.model_validate(outbox.payload)
                assert envelope.message_type == "CustomerUpdated"
                assert envelope.payload == {
                    "customer_id": customer["id"],
                    "changed_fields": ["legal_name", "status", "trade_name"],
                    "version": 3,
                }
                assert envelope.aggregate_version == 3
                assert envelope.correlation_id == audit.correlation_id == correlation_id
                assert envelope.request_id == audit.request_id == request_id
                assert audit.before_snapshot is not None
                assert audit.after_snapshot is not None
                assert "identity_value" not in audit.before_snapshot
                assert "identity_value" not in audit.after_snapshot

        assert api.client.portal is not None
        api.client.portal.call(verify)


def test_patch_requires_update_permission_scope_and_if_match() -> None:
    with customer_api() as api:
        customer = create_customer(api)
        assert api.resolver.context is not None
        api.resolver.context = replace(api.resolver.context, permissions=frozenset({CUSTOMER_READ}))
        headers = {**api.headers, "If-Match": '"1"'}
        assert (
            api.client.patch(
                f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
                json={"legal_name": "Sem permissao"},
                headers=headers,
            ).status_code
            == 403
        )
        allow_update(api)
        assert (
            api.client.patch(
                f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
                json={"legal_name": "Sem etag"},
                headers=api.headers,
            ).status_code
            == 428
        )
        assert (
            api.client.patch(
                f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
                json={"legal_name": "Etag invalido"},
                headers={**api.headers, "If-Match": "1"},
            ).status_code
            == 400
        )
        assert (
            api.client.patch(
                f"/api/v1/customers/{customer['id']}?company_id={api.data.other_company_id}",
                json={"legal_name": "Outra empresa"},
                headers=headers,
            ).status_code
            == 404
        )


def test_patch_missing_customer_returns_not_found_without_effects() -> None:
    with customer_api() as api:
        allow_update(api)
        response = api.client.patch(
            f"/api/v1/customers/{uuid4()}?company_id={api.data.company_id}",
            json={"legal_name": "Inexistente"},
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
        assert update_counts(api) == (0, 0)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"legal_name": None},
        {"status": None},
        {"identity_value": "15350946056"},
        {"customer_type": "COMPANY"},
        {"status": "UNKNOWN"},
        {"trade_name": " "},
    ],
)
def test_patch_rejects_empty_invalid_or_mass_assigned_fields(payload: dict[str, object]) -> None:
    with customer_api() as api:
        customer = create_customer(api)
        response = api.client.patch(
            f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
            json=payload,
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert response.status_code == 422
        assert update_counts(api) == (0, 0)


def test_patch_stale_version_forbidden_status_and_noop_are_stable() -> None:
    with customer_api() as api:
        customer = create_customer(api)
        stale = api.client.patch(
            f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
            json={"legal_name": "Stale"},
            headers={**api.headers, "If-Match": '"2"'},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
        noop = api.client.patch(
            f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
            json={"legal_name": customer["legal_name"]},
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert noop.status_code == 200
        assert noop.json()["event_id"] is None
        assert noop.headers["etag"] == '"1"'
        blocked = api.client.patch(
            f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
            json={"status": "BLOCKED"},
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert blocked.status_code == 200
        forbidden = api.client.patch(
            f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
            json={"status": "INACTIVE"},
            headers={**api.headers, "If-Match": '"2"'},
        )
        assert forbidden.status_code == 422
        assert forbidden.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("component", "method"), [(AuditService, "record"), (OutboxService, "enqueue")]
)
def test_failed_update_effect_rolls_back_customer(
    monkeypatch: pytest.MonkeyPatch,
    component: type[Any],
    method: str,
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Forced customer update failure")

    with customer_api() as api:
        customer = create_customer(api)
        with monkeypatch.context() as patch:
            patch.setattr(component, method, fail)
            with pytest.raises(RuntimeError, match="Forced customer update failure"):
                api.client.patch(
                    f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
                    json={"legal_name": "Rollback"},
                    headers={**api.headers, "If-Match": '"1"'},
                )
        current = api.client.get(
            f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert current.json()["legal_name"] == customer["legal_name"]
        assert update_counts(api) == (0, 0)


def test_concurrent_patch_requests_have_one_version_winner() -> None:
    with customer_api() as api:
        customer = create_customer(api)

        def request(name: str) -> tuple[int, str]:
            response = api.client.patch(
                f"/api/v1/customers/{customer['id']}?company_id={api.data.company_id}",
                json={"legal_name": name},
                headers={**api.headers, "If-Match": '"1"'},
            )
            return response.status_code, response.json()["error"][
                "code"
            ] if response.status_code != 200 else name

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request, ("Winner A", "Winner B")))
        assert sorted(status for status, _ in results) == [200, 409]
        assert any(code == "VERSION_CONFLICT" for status, code in results if status == 409)
        assert update_counts(api) == (1, 1)
