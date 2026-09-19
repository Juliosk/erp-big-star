"""M15 quote API tests with real PostgreSQL and stubbed identity only."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.customer.infrastructure import CustomerModel
from erp.modules.sales.application import SALES_QUOTE_CREATE, SALES_QUOTE_READ
from erp.modules.sales.infrastructure import (
    QuoteRevisionItemModel,
    QuoteRevisionModel,
    SalesQuoteModel,
)
from tests.integration.test_product_persistence import Fixture, fixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "sales-test-token" else None


@dataclass
class SalesApiFixture:
    client: TestClient
    data: Fixture
    customer_id: str
    resolver: ResolverStub

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer sales-test-token"}


async def _seed_customer(data: Fixture) -> str:
    customer_id = uuid4()
    async with data.database.session() as session, session.begin():
        session.add(
            CustomerModel(
                id=customer_id,
                company_id=data.company_id,
                customer_type="COMPANY",
                identity_type="CNPJ",
                identity_value=f"{uuid4().int % 100_000_000_000_000:014d}",
                legal_name="Quote API customer",
                trade_name=None,
                status="ACTIVE",
                version=1,
                created_by=data.actor_id,
                updated_by=data.actor_id,
            )
        )
    return str(customer_id)


async def _cleanup(data: Fixture) -> None:
    company_ids = (data.company_id, data.other_company_id)
    async with data.database.session() as session, session.begin():
        await session.execute(delete(QuoteRevisionItemModel).where(QuoteRevisionItemModel.company_id.in_(company_ids)))
        await session.execute(delete(QuoteRevisionModel).where(QuoteRevisionModel.company_id.in_(company_ids)))
        await session.execute(delete(SalesQuoteModel).where(SalesQuoteModel.company_id.in_(company_ids)))
        await session.execute(delete(CustomerModel).where(CustomerModel.company_id.in_(company_ids)))


@contextmanager
def sales_api() -> Iterator[SalesApiFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = fixture()
        data = client.portal.call(manager.__aenter__)
        customer_id = client.portal.call(_seed_customer, data)
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset({SALES_QUOTE_CREATE, SALES_QUOTE_READ}),
            scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
        )
        try:
            yield SalesApiFixture(client, data, customer_id, resolver)
        finally:
            try:
                client.portal.call(_cleanup, data)
            finally:
                client.portal.call(manager.__aexit__, None, None, None)


def test_quote_api_create_list_detail_and_tenant_scope() -> None:
    with sales_api() as api:
        created = api.client.post(
            "/api/v1/sales/quotes",
            headers=api.headers,
            json={
                "company_id": str(api.data.company_id),
                "number": "Q-API-001",
                "customer_id": api.customer_id,
            },
        )
        assert created.status_code == 201
        assert created.headers["etag"] == '"1"'
        quote_id = created.json()["id"]

        listed = api.client.get(
            f"/api/v1/sales/quotes?company_id={api.data.company_id}", headers=api.headers
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["data"]] == [quote_id]

        detail = api.client.get(
            f"/api/v1/sales/quotes/{quote_id}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert detail.status_code == 200
        assert detail.json()["quote"]["number"] == "Q-API-001"
        assert detail.json()["revisions"] == []

        foreign = api.client.get(
            f"/api/v1/sales/quotes?company_id={api.data.other_company_id}",
            headers=api.headers,
        )
        assert foreign.status_code == 404
        assert foreign.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_quote_api_enforces_rbac_and_error_contract() -> None:
    with sales_api() as api:
        assert api.resolver.context is not None
        api.resolver.context = SecurityContext(
            principal=api.resolver.context.principal,
            permissions=frozenset(),
            scopes=api.resolver.context.scopes,
        )
        denied = api.client.get(
            f"/api/v1/sales/quotes?company_id={api.data.company_id}", headers=api.headers
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PERMISSION_FORBIDDEN"
