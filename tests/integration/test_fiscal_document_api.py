"""M11 fiscal document REST API integration against real PostgreSQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.fiscal.application import FISCAL_NFE_ISSUE, FISCAL_NFE_READ
from erp.platform.config import get_settings
from tests.integration.test_fiscal_document_repository import fiscal_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "fiscal-test-token" else None


@dataclass
class FiscalApiFixture:
    client: TestClient
    data: ProcurementFixture
    resolver: ResolverStub

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer fiscal-test-token"}

    @property
    def collection_url(self) -> str:
        return f"/api/v1/fiscal/documents?company_id={self.data.company_id}"


@contextmanager
def fiscal_api() -> Iterator[FiscalApiFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = fiscal_fixture()
        data, _ = client.portal.call(manager.__aenter__)
        resolver.context = _context(data)
        try:
            yield FiscalApiFixture(client, data, resolver)
        finally:
            client.portal.call(manager.__aexit__, None, None, None)


def _context(
    data: ProcurementFixture, *, permissions: frozenset[Any] | None = None
) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=permissions or frozenset({FISCAL_NFE_READ, FISCAL_NFE_ISSUE}),
        scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
    )


def _component(amount: str) -> dict[str, str]:
    return {"tax_code": "00", "taxable_base": "20", "rate": "1", "amount": amount}


def document_body(api: FiscalApiFixture, *, number: int = 123) -> dict[str, Any]:
    party = {
        "tax_id": "12345678000195",
        "legal_name": "Big Star Brinquedos",
        "state_registration": "123",
        "street": "Rua Fiscal",
        "number": "100",
        "district": "Centro",
        "city": "Sao Paulo",
        "state_code": "SP",
        "postal_code": "01001000",
        "country_code": "BR",
    }
    recipient = {**party, "tax_id": "52998224725", "legal_name": "Cliente Fiscal"}
    return {
        "company_id": str(api.data.company_id),
        "model": "55",
        "series": 1,
        "number": number,
        "issuer": party,
        "recipient": recipient,
        "items": [
            {
                "product_id": str(uuid4()),
                "code": "SKU-1",
                "description": "Produto fiscal",
                "ncm": "95030099",
                "cfop": "5102",
                "unit_of_measure": "UN",
                "quantity": "2",
                "unit_price": "10",
                "freight_amount": "1",
                "discount_amount": "2",
                "total_amount": "19",
                "taxes": {
                    "icms": _component("1"),
                    "pis": _component("0.10"),
                    "cofins": _component("0.20"),
                    "ipi": _component("0.30"),
                },
            }
        ],
    }


def create_document(api: FiscalApiFixture, *, number: int = 123) -> Any:
    response = api.client.post(
        "/api/v1/fiscal/documents", json=document_body(api, number=number), headers=api.headers
    )
    assert response.status_code == 201, response.text
    return response


def test_create_and_get_full_fiscal_document_contract() -> None:
    with fiscal_api() as api:
        created = create_document(api)
        body = created.json()
        assert created.headers["etag"] == '"1"'
        assert created.headers["location"].endswith(
            f"{body['id']}?company_id={api.data.company_id}"
        )
        assert body["status"] == "DRAFT"
        assert body["items"][0]["taxes"]["icms"]["amount"] == "1.00"

        detail = api.client.get(
            f"/api/v1/fiscal/documents/{body['id']}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"1"'
        assert detail.json() == body


def test_issue_is_idempotent_and_rejects_stale_concurrent_request() -> None:
    with fiscal_api() as api:
        created = create_document(api)
        document_id = created.json()["id"]
        url = f"/api/v1/fiscal/documents/{document_id}/issue?company_id={api.data.company_id}"
        headers = {**api.headers, "If-Match": '"1"', "Idempotency-Key": "issue-1"}

        issued = api.client.post(url, headers=headers)
        assert issued.status_code == 202
        assert issued.json()["status"] == "ISSUING"
        assert issued.headers["etag"] == '"2"'
        assert issued.headers["idempotency-replayed"] == "false"

        replay = api.client.post(url, headers=headers)
        assert replay.status_code == 202
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.json()["id"] == document_id

        other_id = create_document(api, number=124).json()["id"]
        reused = api.client.post(
            f"/api/v1/fiscal/documents/{other_id}/issue?company_id={api.data.company_id}",
            headers=headers,
        )
        assert reused.status_code == 409
        assert reused.json()["error"]["code"] == (
            "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"
        )

        stale = api.client.post(
            url,
            headers={**api.headers, "If-Match": '"1"', "Idempotency-Key": "issue-2"},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"

        invalid_transition = api.client.post(
            url,
            headers={**api.headers, "If-Match": '"2"', "Idempotency-Key": "issue-3"},
        )
        assert invalid_transition.status_code == 409
        assert invalid_transition.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_issue_requires_etag_idempotency_and_matching_payload() -> None:
    with fiscal_api() as api:
        created = create_document(api)
        document_id = created.json()["id"]
        url = f"/api/v1/fiscal/documents/{document_id}/issue?company_id={api.data.company_id}"
        missing_etag = api.client.post(
            url, headers={**api.headers, "Idempotency-Key": "issue-required"}
        )
        assert missing_etag.status_code == 428
        assert missing_etag.json()["error"]["code"] == "PRECONDITION_REQUIRED"
        missing_key = api.client.post(url, headers={**api.headers, "If-Match": '"1"'})
        assert missing_key.status_code == 422
        assert missing_key.json()["error"]["code"] == "VALIDATION_ERROR"
        invalid_etag = api.client.post(
            url, headers={**api.headers, "If-Match": "1", "Idempotency-Key": "issue-invalid"}
        )
        assert invalid_etag.status_code == 400
        assert invalid_etag.json()["error"]["code"] == "INVALID_IF_MATCH"

        missing = api.client.post(
            f"/api/v1/fiscal/documents/{uuid4()}/issue?company_id={api.data.company_id}",
            headers={**api.headers, "If-Match": '"1"', "Idempotency-Key": "issue-missing"},
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_paginated_list_supports_status_model_and_period_filters() -> None:
    with fiscal_api() as api:
        first = create_document(api, number=123).json()
        create_document(api, number=124)
        page = api.client.get(
            api.collection_url + "&page_size=1&status=DRAFT&model=55", headers=api.headers
        )
        assert page.status_code == 200
        assert page.json()["meta"] == {"page": 1, "page_size": 1, "has_more": True}
        assert page.json()["data"][0]["id"] == first["id"]

        now = datetime.now(UTC)
        period = api.client.get(
            "/api/v1/fiscal/documents",
            params={
                "company_id": str(api.data.company_id),
                "created_from": (now - timedelta(minutes=1)).isoformat(),
                "created_to": (now + timedelta(minutes=1)).isoformat(),
            },
            headers=api.headers,
        )
        assert period.status_code == 200
        assert len(period.json()["data"]) == 2
        by_access_key = api.client.get(
            api.collection_url + "&access_key=" + "0" * 44, headers=api.headers
        )
        assert by_access_key.status_code == 200
        assert by_access_key.json()["data"] == []


def test_invalid_business_payload_filter_and_duplicate_identity_use_error_contract() -> None:
    with fiscal_api() as api:
        body = document_body(api)
        body["totals"] = {
            "products_amount": "999",
            "freight_amount": "1",
            "discount_amount": "2",
            "tax_amount": "1.60",
            "total_amount": "19",
        }
        invalid = api.client.post("/api/v1/fiscal/documents", json=body, headers=api.headers)
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"

        create_document(api)
        duplicate = api.client.post(
            "/api/v1/fiscal/documents", json=document_body(api), headers=api.headers
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "FISCAL_DOCUMENT_CONFLICT"

        reversed_period = api.client.get(
            api.collection_url
            + "&created_from=2026-10-06T00:00:00Z&created_to=2026-10-05T00:00:00Z",
            headers=api.headers,
        )
        assert reversed_period.status_code == 422
        assert reversed_period.json()["error"]["code"] == "VALIDATION_ERROR"
        blank_key = api.client.get(api.collection_url + "&access_key=%20", headers=api.headers)
        assert blank_key.status_code == 422
        assert blank_key.json()["error"]["code"] == "VALIDATION_ERROR"

        missing = api.client.get(
            f"/api/v1/fiscal/documents/{uuid4()}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_rbac_authentication_and_unavailable_service_fail_closed() -> None:
    with fiscal_api() as api:
        assert api.client.get(api.collection_url).status_code == 401
        invalid_token = api.client.get(
            api.collection_url, headers={"Authorization": "Bearer wrong-token"}
        )
        assert invalid_token.status_code == 401
        application = cast(FastAPI, api.client.app)
        saved_resolver = application.state.security_context_resolver
        application.state.security_context_resolver = None
        unavailable_auth = api.client.get(api.collection_url, headers=api.headers)
        assert unavailable_auth.status_code == 503
        application.state.security_context_resolver = saved_resolver
        api.resolver.context = _context(api.data, permissions=frozenset({FISCAL_NFE_READ}))
        denied = api.client.post(
            "/api/v1/fiscal/documents", json=document_body(api), headers=api.headers
        )
        assert denied.status_code == 403
        application.state.fiscal_documents = None
        unavailable = api.client.get(api.collection_url, headers=api.headers)
        assert unavailable.status_code == 503
        assert unavailable.json()["error"]["code"] == "FISCAL_SERVICE_UNAVAILABLE"


def test_cross_tenant_reads_and_mutations_are_not_enumerable() -> None:
    with fiscal_api() as api:
        created = create_document(api).json()
        other = api.data.other_company_id
        detail = api.client.get(
            f"/api/v1/fiscal/documents/{created['id']}?company_id={other}", headers=api.headers
        )
        assert detail.status_code == 404
        issue = api.client.post(
            f"/api/v1/fiscal/documents/{created['id']}/issue?company_id={other}",
            headers={**api.headers, "If-Match": '"1"', "Idempotency-Key": "cross-tenant"},
        )
        assert issue.status_code == 404

