"""M6 supplier REST API integration tests against real PostgreSQL."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.procurement.application import (
    PROCUREMENT_SUPPLIER_MANAGE,
    PROCUREMENT_SUPPLIER_READ,
    SupplierService,
)
from erp.platform.config import get_settings
from erp.platform.errors import ApplicationError
from tests.integration.test_procurement_supplier_repository import (
    ProcurementFixture,
    _cnpj,
    procurement_fixture,
)

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "procurement-test-token" else None


@dataclass
class ProcurementApiFixture:
    client: TestClient
    data: ProcurementFixture
    resolver: ResolverStub

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer procurement-test-token"}

    @property
    def url(self) -> str:
        return f"/api/v1/procurement/suppliers?company_id={self.data.company_id}"


@contextmanager
def procurement_api() -> Iterator[ProcurementApiFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = procurement_fixture()
        data = client.portal.call(manager.__aenter__)
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset({PROCUREMENT_SUPPLIER_READ, PROCUREMENT_SUPPLIER_MANAGE}),
            scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
        )
        try:
            yield ProcurementApiFixture(client, data, resolver)
        finally:
            client.portal.call(manager.__aexit__, None, None, None)


def supplier_body(api: ProcurementApiFixture, *, document: str | None = None) -> dict[str, Any]:
    return {
        "company_id": str(api.data.company_id),
        "kind": "COMPANY",
        "identity_kind": "CNPJ",
        "identity_value": document or _cnpj(),
        "identity_country_code": "BR",
        "legal_name": "Fornecedor API",
        "trade_name": "Fornecedor",
        "sites": [
            {
                "code": "MATRIZ",
                "name": "Matriz Sao Paulo",
                "line1": "Rua das Compras, 100",
                "city": "Sao Paulo",
                "country_code": "BR",
                "state": "SP",
                "postal_code": "01001000",
                "email": "compras@fornecedor.example",
                "phone": "+55 11 3333-4444",
                "is_primary": True,
            }
        ],
    }


def create_supplier(api: ProcurementApiFixture, *, document: str | None = None) -> Any:
    response = api.client.post(
        "/api/v1/procurement/suppliers",
        json=supplier_body(api, document=document),
        headers=api.headers,
    )
    assert response.status_code == 201
    return response


def test_create_detail_and_complete_site_contract() -> None:
    with procurement_api() as api:
        response = create_supplier(api)
        body = response.json()
        assert response.headers["etag"] == '"2"'
        assert response.headers["location"].endswith(
            f"{body['id']}?company_id={api.data.company_id}"
        )
        assert body["identity_ref"].endswith(body["identity_value"][-4:])
        assert body["sites"][0]["code"] == "MATRIZ"
        assert body["sites"][0]["address"]["postal_code"] == "01001000"

        detail = api.client.get(
            f"/api/v1/procurement/suppliers/{body['id']}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"2"'
        assert detail.json() == body


def test_create_without_sites_and_domain_validation_error() -> None:
    with procurement_api() as api:
        body = supplier_body(api)
        body["sites"] = []
        created = api.client.post("/api/v1/procurement/suppliers", json=body, headers=api.headers)
        assert created.status_code == 201
        assert created.headers["etag"] == '"1"'
        assert created.json()["sites"] == []

        invalid = supplier_body(api)
        invalid["identity_kind"] = "CPF"
        invalid["identity_value"] = "52998224725"
        rejected = api.client.post(
            "/api/v1/procurement/suppliers", json=invalid, headers=api.headers
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"


def test_paginated_list_filters_status_and_normalized_document() -> None:
    with procurement_api() as api:
        document = _cnpj()
        first = create_supplier(api, document=document).json()
        body = supplier_body(api)
        body["legal_name"] = "Segundo fornecedor"
        body["sites"][0]["code"] = "FILIAL"
        second = api.client.post("/api/v1/procurement/suppliers", json=body, headers=api.headers)
        assert second.status_code == 201

        page = api.client.get(api.url + "&page_size=1", headers=api.headers)
        assert page.status_code == 200
        assert page.json()["meta"] == {"page": 1, "page_size": 1, "has_more": True}
        filtered = api.client.get(
            api.url
            + "&document="
            + f"{document[:2]}.{document[2:5]}.{document[5:8]}/{document[8:12]}-{document[12:]}",
            headers=api.headers,
        )
        assert [item["id"] for item in filtered.json()["data"]] == [first["id"]]
        assert api.client.get(api.url + "&status=ACTIVE", headers=api.headers).status_code == 200


def test_patch_master_data_status_and_etag() -> None:
    with procurement_api() as api:
        created = create_supplier(api)
        supplier = created.json()
        response = api.client.patch(
            f"/api/v1/procurement/suppliers/{supplier['id']}?company_id={api.data.company_id}",
            json={"legal_name": "Fornecedor atualizado", "trade_name": None, "status": "BLOCKED"},
            headers={**api.headers, "If-Match": created.headers["etag"]},
        )
        assert response.status_code == 200
        assert response.headers["etag"] == '"4"'
        assert response.json()["legal_name"] == "Fornecedor atualizado"
        assert response.json()["trade_name"] is None
        assert response.json()["status"] == "BLOCKED"


def test_rbac_scope_and_cross_company_ids_fail_closed() -> None:
    with procurement_api() as api:
        created = create_supplier(api).json()
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context, permissions=frozenset({PROCUREMENT_SUPPLIER_READ})
        )
        denied = api.client.post(
            "/api/v1/procurement/suppliers", json=supplier_body(api), headers=api.headers
        )
        assert denied.status_code == 403
        api.resolver.context = replace(api.resolver.context, permissions=frozenset())
        assert api.client.get(api.url, headers=api.headers).status_code == 403
        api.resolver.context = replace(
            api.resolver.context,
            permissions=frozenset({PROCUREMENT_SUPPLIER_READ}),
        )
        foreign_detail = api.client.get(
            f"/api/v1/procurement/suppliers/{created['id']}?company_id={api.data.other_company_id}",
            headers=api.headers,
        )
        assert foreign_detail.status_code == 404


def test_patch_requires_valid_if_match_and_reports_stale_version() -> None:
    with procurement_api() as api:
        supplier = create_supplier(api).json()
        url = f"/api/v1/procurement/suppliers/{supplier['id']}?company_id={api.data.company_id}"
        missing = api.client.patch(url, json={"legal_name": "Missing"}, headers=api.headers)
        assert missing.status_code == 428
        assert missing.json()["error"]["code"] == "PRECONDITION_REQUIRED"
        malformed = api.client.patch(
            url,
            json={"legal_name": "Malformed"},
            headers={**api.headers, "If-Match": "2"},
        )
        assert malformed.status_code == 400
        stale = api.client.patch(
            url,
            json={"legal_name": "Stale"},
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"


def test_patch_missing_supplier_and_noop_paths() -> None:
    with procurement_api() as api:
        missing = api.client.patch(
            f"/api/v1/procurement/suppliers/{uuid4()}?company_id={api.data.company_id}",
            json={"legal_name": "Missing"},
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert missing.status_code == 404
        created = create_supplier(api)
        supplier = created.json()
        noop = api.client.patch(
            f"/api/v1/procurement/suppliers/{supplier['id']}?company_id={api.data.company_id}",
            json={"legal_name": supplier["legal_name"]},
            headers={**api.headers, "If-Match": created.headers["etag"]},
        )
        assert noop.status_code == 200
        assert noop.headers["etag"] == created.headers["etag"]


def test_error_contract_for_duplicate_invalid_transition_and_not_found() -> None:
    with procurement_api() as api:
        document = _cnpj()
        first = create_supplier(api, document=document)
        duplicate = api.client.post(
            "/api/v1/procurement/suppliers",
            json=supplier_body(api, document=document),
            headers=api.headers,
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "SUPPLIER_CONFLICT"

        supplier = first.json()
        url = f"/api/v1/procurement/suppliers/{supplier['id']}?company_id={api.data.company_id}"
        blocked = api.client.patch(
            url,
            json={"status": "BLOCKED"},
            headers={**api.headers, "If-Match": first.headers["etag"]},
        )
        forbidden = api.client.patch(
            url,
            json={"status": "INACTIVE"},
            headers={**api.headers, "If-Match": blocked.headers["etag"]},
        )
        assert forbidden.status_code == 422
        assert forbidden.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"
        missing = api.client.get(
            f"/api/v1/procurement/suppliers/{uuid4()}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_concurrent_patch_has_exactly_one_version_winner() -> None:
    with procurement_api() as api:
        created = create_supplier(api)
        supplier = created.json()
        url = f"/api/v1/procurement/suppliers/{supplier['id']}?company_id={api.data.company_id}"

        def request(name: str) -> tuple[int, str]:
            response = api.client.patch(
                url,
                json={"legal_name": name},
                headers={**api.headers, "If-Match": created.headers["etag"]},
            )
            body = cast(dict[str, Any], response.json())
            return response.status_code, (
                name if response.status_code == 200 else body["error"]["code"]
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request, ("Winner A", "Winner B")))
        assert sorted(status for status, _ in results) == [200, 409]
        assert any(code == "VERSION_CONFLICT" for status, code in results if status == 409)


def test_authentication_and_service_failures_use_official_error_contract() -> None:
    with procurement_api() as api:
        missing = api.client.get(api.url)
        assert missing.status_code == 401
        assert missing.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
        invalid = api.client.get(api.url, headers={"Authorization": "Bearer wrong"})
        assert invalid.status_code == 401
        assert invalid.headers["www-authenticate"] == "Bearer"

        app = cast(FastAPI, api.client.app)
        resolver = app.state.security_context_resolver
        app.state.security_context_resolver = None
        try:
            unavailable = api.client.get(api.url, headers=api.headers)
            assert unavailable.status_code == 503
            assert unavailable.json()["error"]["code"] == "AUTHENTICATION_UNAVAILABLE"
        finally:
            app.state.security_context_resolver = resolver

        service = app.state.procurement_suppliers
        app.state.procurement_suppliers = None
        try:
            unavailable = api.client.get(api.url, headers=api.headers)
            assert unavailable.status_code == 503
            assert unavailable.json()["error"]["code"] == "PROCUREMENT_SUPPLIER_UNAVAILABLE"
        finally:
            app.state.procurement_suppliers = service


def test_application_validation_paths_remain_stable_below_http_boundary() -> None:
    with procurement_api() as api:
        assert api.client.portal is not None
        assert api.resolver.context is not None
        context = api.resolver.context
        service = cast(SupplierService, cast(FastAPI, api.client.app).state.procurement_suppliers)

        async def verify() -> None:
            with pytest.raises(ApplicationError) as pagination:
                await service.list(context, api.data.company_id, page=0)
            assert pagination.value.code == "VALIDATION_ERROR"
            with pytest.raises(ApplicationError) as document:
                await service.list(context, api.data.company_id, document=" ")
            assert document.value.code == "VALIDATION_ERROR"
            result = await service.list(
                context, api.data.company_id, document="foreign-ref"
            )
            assert result.items == ()

        api.client.portal.call(verify)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"legal_name": None},
        {"status": None},
        {"identity_value": "52998224725"},
        {"status": "UNKNOWN"},
    ],
)
def test_patch_rejects_empty_invalid_and_mass_assigned_payloads(
    payload: dict[str, object],
) -> None:
    with procurement_api() as api:
        created = create_supplier(api)
        supplier = created.json()
        response = api.client.patch(
            f"/api/v1/procurement/suppliers/{supplier['id']}?company_id={api.data.company_id}",
            json=payload,
            headers={**api.headers, "If-Match": created.headers["etag"]},
        )
        assert response.status_code == 422
