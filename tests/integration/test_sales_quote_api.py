"""M15 quote API tests with real PostgreSQL and stubbed identity only."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.customer.infrastructure import CustomerModel
from erp.modules.product.infrastructure import ProductRepository
from erp.modules.sales.application import (
    SALES_DISCOUNT_REQUEST,
    SALES_QUOTE_CREATE,
    SALES_QUOTE_READ,
    SALES_QUOTE_SEND,
    SALES_QUOTE_UPDATE,
)
from erp.modules.sales.infrastructure import (
    QuoteRevisionItemModel,
    QuoteRevisionModel,
    SalesOrderItemModel,
    SalesOrderModel,
    SalesQuoteModel,
)
from erp.modules.workflow.application import (
    WORKFLOW_DEFINITION_MANAGE,
    WORKFLOW_REQUEST_CREATE,
)
from erp.platform.audit import AuditEventModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_product_persistence import Fixture, fixture
from tests.integration.test_workflow_api import _cleanup_workflow

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
    product_id: str
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


async def _seed_product(data: Fixture) -> str:
    product = data.product(code="QUOTE-API-LINE")
    async with data.database.session() as session, session.begin():
        await ProductRepository(session, company_id=data.company_id).add(
            product, actor_id=data.actor_id
        )
    return str(product.id)


async def _cleanup(data: Fixture) -> None:
    await _cleanup_workflow(data)
    company_ids = (data.company_id, data.other_company_id)
    async with data.database.session() as session, session.begin():
        await session.execute(delete(OutboxEventModel).where(OutboxEventModel.source_module == "sales"))
        await session.execute(delete(AuditEventModel).where(AuditEventModel.module == "sales"))
        await session.execute(delete(SalesOrderItemModel).where(SalesOrderItemModel.company_id.in_(company_ids)))
        await session.execute(delete(SalesOrderModel).where(SalesOrderModel.company_id.in_(company_ids)))
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
        product_id = client.portal.call(_seed_product, data)
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset(
                {
                    SALES_DISCOUNT_REQUEST,
                    SALES_QUOTE_CREATE,
                    SALES_QUOTE_READ,
                    SALES_QUOTE_SEND,
                    SALES_QUOTE_UPDATE,
                    WORKFLOW_DEFINITION_MANAGE,
                    WORKFLOW_REQUEST_CREATE,
                }
            ),
            scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
        )
        try:
            yield SalesApiFixture(client, data, customer_id, product_id, resolver)
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


def test_quote_lifecycle_is_versioned_and_emits_atomic_audit_outbox() -> None:
    with sales_api() as api:
        created = api.client.post(
            "/api/v1/sales/quotes",
            headers=api.headers,
            json={
                "company_id": str(api.data.company_id),
                "number": "Q-LIFECYCLE",
                "customer_id": api.customer_id,
            },
        ).json()
        quote_id = created["id"]
        revision = api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/revisions",
            headers={**api.headers, "If-Match": '"1"'},
            json={
                "company_id": str(api.data.company_id),
                "lines": [
                    {
                        "product_id": api.product_id,
                        "quantity": "2.000000",
                        "unit_price": "25.00",
                        "discount_amount": "5.00",
                    }
                ],
            },
        )
        assert revision.status_code == 200
        assert revision.headers["etag"] == '"2"'
        assert revision.json()["detail"]["quote"]["current_revision_number"] == 1

        missing_match = api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/send",
            headers=api.headers,
            json={"company_id": str(api.data.company_id)},
        )
        assert missing_match.status_code == 428

        sent = api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/send",
            headers={**api.headers, "If-Match": '"2"'},
            json={"company_id": str(api.data.company_id)},
        )
        assert sent.status_code == 200
        assert sent.headers["etag"] == '"3"'
        assert sent.json()["detail"]["quote"]["status"] == "SENT"

        stale = api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/accept",
            headers={**api.headers, "If-Match": '"2"'},
            json={"company_id": str(api.data.company_id)},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"

        accepted = api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/accept-partially",
            headers={**api.headers, "If-Match": '"3"'},
            json={"company_id": str(api.data.company_id)},
        )
        assert accepted.status_code == 200
        assert accepted.json()["detail"]["quote"]["status"] == "PARTIALLY_ACCEPTED"

        async def counts() -> tuple[int, int]:
            async with api.data.database.session() as session:
                audits = await session.scalar(
                    select(func.count()).select_from(AuditEventModel).where(
                        AuditEventModel.module == "sales"
                    )
                )
                events = await session.scalar(
                    select(func.count()).select_from(OutboxEventModel).where(
                        OutboxEventModel.source_module == "sales"
                    )
                )
                return int(audits or 0), int(events or 0)

        assert api.client.portal is not None
        assert api.client.portal.call(counts) == (3, 3)


def test_discount_exception_opens_m22_workflow_and_links_quote() -> None:
    with sales_api() as api:
        definition = api.client.post(
            "/api/v1/workflow/definitions",
            headers=api.headers,
            json={
                "company_id": str(api.data.company_id),
                "code": "SALES-DISCOUNT",
                "name": "Alçada comercial",
                "source_module": "SALES",
                "source_type": "QUOTE_DISCOUNT",
                "approval_mode": "SEQUENTIAL",
                "steps": [
                    {
                        "sequence": 1,
                        "code": "MANAGER",
                        "name": "Gerência comercial",
                        "required_permission": "workflow.approval.decide",
                        "threshold_amount": "1.00",
                    }
                ],
            },
        )
        assert definition.status_code == 201
        created = api.client.post(
            "/api/v1/sales/quotes",
            headers=api.headers,
            json={
                "company_id": str(api.data.company_id),
                "number": "Q-DISCOUNT",
                "customer_id": api.customer_id,
            },
        ).json()
        quote_id = created["id"]
        revised = api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/revisions",
            headers={**api.headers, "If-Match": '"1"'},
            json={
                "company_id": str(api.data.company_id),
                "lines": [
                    {
                        "product_id": api.product_id,
                        "quantity": "1.000000",
                        "unit_price": "100.00",
                        "discount_amount": "10.00",
                    }
                ],
            },
        )
        assert revised.status_code == 200

        requested = api.client.post(
            f"/api/v1/sales/quotes/{quote_id}/discount-approval",
            headers={**api.headers, "If-Match": '"2"'},
            json={"company_id": str(api.data.company_id)},
        )
        assert requested.status_code == 200
        body = requested.json()
        workflow_id = body["detail"]["quote"]["workflow_instance_id"]
        assert workflow_id is not None
        assert requested.headers["etag"] == '"3"'

        workflow = api.client.get(
            f"/api/v1/workflow/instances/{workflow_id}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert workflow.status_code == 403  # read permission remains independently governed
