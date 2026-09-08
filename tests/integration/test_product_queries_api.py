"""Authorized product HTTP queries against the real tenant-bound read adapter."""

from dataclasses import replace
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from erp.apps.api.app import create_app
from erp.modules.admin.domain import Branch, Scope, ScopeType
from erp.modules.admin.infrastructure import BranchModel, BranchRepository, CompanyModel
from erp.modules.product.application import ProductQueries
from erp.modules.product.application.permissions import PRODUCT_CREATE
from erp.modules.product.domain import ProductLifecycle
from erp.modules.product.infrastructure import ProductRepository
from erp.platform.config import get_settings
from erp.platform.errors import ApplicationError
from tests.integration.product_api_support import product_api
from tests.integration.test_product_persistence import _cnpj

pytestmark = pytest.mark.integration


def test_application_rejects_invalid_pagination_without_http_validation() -> None:
    with product_api() as api:

        async def verify() -> None:
            assert api.resolver.context is not None
            queries = cast(ProductQueries, cast(FastAPI, api.client.app).state.product_queries)
            with pytest.raises(ApplicationError) as captured:
                await queries.list(api.resolver.context, api.data.company_id, page=0)
            assert captured.value.code == "VALIDATION_ERROR"

        assert api.client.portal is not None
        api.client.portal.call(verify)


def test_query_pages_detail_etag_and_company_isolation() -> None:
    with product_api() as api:
        own = api.data.product(code="A")
        other = api.data.product(other_company=True)

        async def seed() -> None:
            async with api.data.database.session() as session, session.begin():
                await ProductRepository(session, company_id=own.company_id).add(
                    own, actor_id=api.data.actor_id
                )
                await ProductRepository(session, company_id=own.company_id).add(
                    api.data.product(code="B"), actor_id=api.data.actor_id
                )
                await ProductRepository(session, company_id=other.company_id).add(
                    other, actor_id=api.data.actor_id
                )

        assert api.client.portal is not None
        api.client.portal.call(seed)
        response = api.client.get(api.url + "&page_size=1", headers=api.headers)
        assert response.status_code == 200
        assert response.json()["data"][0]["id"] == str(own.id)
        assert response.json()["meta"] == {"page": 1, "page_size": 1, "has_more": True}
        last = api.client.get(api.url + "&page_size=1&page=2", headers=api.headers)
        assert last.json()["data"][0]["code"] == "B"
        assert last.json()["meta"]["has_more"] is False
        assert api.client.get(api.url + "&page=3", headers=api.headers).json()["data"] == []
        assert (
            api.client.get(
                api.url + f"&lifecycle={ProductLifecycle.ATIVO}", headers=api.headers
            ).json()["data"]
            == []
        )
        detail = api.client.get(
            f"/api/v1/products/{own.id}?company_id={own.company_id}", headers=api.headers
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"1"'
        assert detail.headers["cache-control"] == "no-store"
        for product_id in (other.id, uuid4()):
            hidden = api.client.get(
                f"/api/v1/products/{product_id}?company_id={own.company_id}", headers=api.headers
            )
            assert hidden.status_code == 404
            assert hidden.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
        denied_company = api.client.get(
            f"/api/v1/products?company_id={other.company_id}", headers=api.headers
        )
        assert denied_company.status_code == 404


@pytest.mark.parametrize("query", ["&page=0", "&page_size=0", "&page_size=101", "&lifecycle=BAD"])
def test_query_rejects_invalid_pagination_and_filters(query: str) -> None:
    with product_api() as api:
        response = api.client.get(api.url + query, headers=api.headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_query_denies_absent_permission_empty_scope_and_revoked_token() -> None:
    with product_api() as api:
        assert api.resolver.context is not None
        original = api.resolver.context
        assert api.client.get(api.url).status_code == 401
        assert (
            api.client.get(api.url, headers={"Authorization": "Bearer invalid"}).status_code == 401
        )
        api.resolver.context = replace(original, permissions=frozenset())
        forbidden = api.client.get(api.url, headers=api.headers)
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "PERMISSION_FORBIDDEN"
        api.resolver.context = replace(original, scopes=frozenset())
        assert (
            api.client.get(api.url, headers=api.headers).json()["error"]["code"]
            == "SCOPE_FORBIDDEN"
        )
        api.resolver.context = None
        assert api.client.get(api.url, headers=api.headers).status_code == 401


def test_group_and_branch_visibility_are_resolved_by_m1() -> None:
    with product_api() as api:
        assert api.client.portal is not None
        assert api.resolver.context is not None

        async def seed_branch() -> tuple[Scope, Scope]:
            async with api.data.database.session() as session, session.begin():
                group_id = await session.scalar(
                    select(CompanyModel.group_id).where(CompanyModel.id == api.data.company_id)
                )
                assert group_id is not None
                branch = Branch.create(
                    company_id=api.data.company_id,
                    code="TEST",
                    name="Test branch",
                    tax_id=_cnpj(),
                    timezone="America/Sao_Paulo",
                )
                await BranchRepository().add(session, branch, actor_id=api.data.actor_id)
                return Scope(ScopeType.GROUP, group_id), Scope(ScopeType.BRANCH, branch.id)

        scopes = api.client.portal.call(seed_branch)
        try:
            for scope in scopes:
                api.resolver.context = replace(api.resolver.context, scopes=frozenset({scope}))
                assert api.client.get(api.url, headers=api.headers).status_code == 200
            api.resolver.context = replace(
                api.resolver.context, permissions=frozenset({PRODUCT_CREATE})
            )
            denied = api.client.post(
                "/api/v1/products",
                json={
                    "company_id": str(api.data.company_id),
                    "code": "BRANCH-WRITE",
                    "sku": f"BRANCH-{uuid4().hex}",
                    "name": "Forbidden",
                    "product_type": "PA",
                    "uom": "UN",
                },
                headers={**api.headers, "Idempotency-Key": str(uuid4())},
            )
            assert denied.status_code == 404
        finally:

            async def cleanup() -> None:
                from sqlalchemy import delete

                async with api.data.database.session() as session, session.begin():
                    await session.execute(
                        delete(BranchModel).where(BranchModel.id == scopes[1].scope_id)
                    )

            api.client.portal.call(cleanup)


def test_missing_identity_adapter_remains_fail_closed() -> None:
    with TestClient(create_app(get_settings())) as client:
        response = client.get(
            f"/api/v1/products?company_id={uuid4()}",
            headers={"Authorization": "Bearer not-a-token"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "AUTHENTICATION_UNAVAILABLE"
