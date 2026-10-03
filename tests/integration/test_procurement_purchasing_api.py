"""M6 requisition and purchase order API tests against PostgreSQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.procurement.application import (
    PROCUREMENT_ORDER_MANAGE,
    PROCUREMENT_ORDER_READ,
    PROCUREMENT_REQUISITION_MANAGE,
    PROCUREMENT_REQUISITION_READ,
    PROCUREMENT_SUPPLIER_MANAGE,
)
from erp.platform.config import get_settings
from tests.integration.test_procurement_purchasing_repository import purchasing_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture, _cnpj

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "purchasing-test-token" else None


@dataclass
class PurchasingApiFixture:
    client: TestClient
    data: ProcurementFixture
    product_id: UUID
    resolver: ResolverStub

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer purchasing-test-token"}


@contextmanager
def purchasing_api() -> Iterator[PurchasingApiFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = purchasing_fixture()
        data, product, _ = client.portal.call(manager.__aenter__)
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset(
                {
                    PROCUREMENT_SUPPLIER_MANAGE,
                    PROCUREMENT_REQUISITION_READ,
                    PROCUREMENT_REQUISITION_MANAGE,
                    PROCUREMENT_ORDER_READ,
                    PROCUREMENT_ORDER_MANAGE,
                }
            ),
            scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
        )
        try:
            yield PurchasingApiFixture(client, data, product.id, resolver)
        finally:
            client.portal.call(manager.__aexit__, None, None, None)


def requisition_body(api: PurchasingApiFixture) -> dict[str, Any]:
    return {
        "company_id": str(api.data.company_id),
        "number": f"PR-{uuid4().hex[:10]}",
        "cost_center_id": str(uuid4()),
        "justification": "Reposicao para vendas",
        "items": [
            {
                "product_id": str(api.product_id),
                "quantity": "10.000000",
                "unit_of_measure": "UN",
                "needed_by": (datetime.now(UTC).date() + timedelta(days=10)).isoformat(),
                "urgency": "HIGH",
                "specification": "Produto aprovado",
            }
        ],
    }


def create_requisition(api: PurchasingApiFixture) -> Any:
    response = api.client.post(
        "/api/v1/procurement/requisitions", json=requisition_body(api), headers=api.headers
    )
    assert response.status_code == 201
    assert response.headers["etag"] == '"1"'
    return response


def action(
    api: PurchasingApiFixture,
    resource: str,
    resource_id: str,
    name: str,
    etag: str,
    body: dict[str, Any] | None = None,
) -> Any:
    return api.client.post(
        f"/api/v1/procurement/{resource}/{resource_id}/{name}?company_id={api.data.company_id}",
        json=body,
        headers={**api.headers, "If-Match": etag},
    )


def approve_requisition(api: PurchasingApiFixture) -> Any:
    created = create_requisition(api)
    submitted = action(api, "requisitions", created.json()["id"], "submit", created.headers["etag"])
    assert submitted.status_code == 200
    approved = action(
        api, "requisitions", created.json()["id"], "approve", submitted.headers["etag"]
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    return approved


def create_supplier(api: PurchasingApiFixture) -> Any:
    response = api.client.post(
        "/api/v1/procurement/suppliers",
        headers=api.headers,
        json={
            "company_id": str(api.data.company_id),
            "kind": "COMPANY",
            "identity_kind": "CNPJ",
            "identity_value": _cnpj(),
            "identity_country_code": "BR",
            "legal_name": "Fornecedor de compras",
            "sites": [],
        },
    )
    assert response.status_code == 201
    return response


def create_order(api: PurchasingApiFixture, requisition: Any, supplier: Any) -> Any:
    response = api.client.post(
        "/api/v1/procurement/purchase-orders",
        headers=api.headers,
        json={
            "company_id": str(api.data.company_id),
            "number": f"PO-{uuid4().hex[:10]}",
            "source_requisition_id": requisition.json()["id"],
            "supplier_id": supplier.json()["id"],
            "currency": "BRL",
            "payment_terms_code": "30D",
            "payment_terms_description": "Trinta dias",
            "installment_days": [30],
            "items": [
                {
                    "requisition_item_id": requisition.json()["items"][0]["id"],
                    "quantity": "10",
                    "unit_price": "12.34",
                }
            ],
        },
    )
    assert response.status_code == 201
    return response


def test_complete_requisition_lifecycle_detail_filters_and_etags() -> None:
    with purchasing_api() as api:
        created = create_requisition(api)
        body = created.json()
        detail = api.client.get(
            f"/api/v1/procurement/requisitions/{body['id']}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"1"'
        assert detail.json()["items"][0]["product_id"] == str(api.product_id)
        submitted = action(api, "requisitions", body["id"], "submit", '"1"')
        approved = action(api, "requisitions", body["id"], "approve", submitted.headers["etag"])
        assert approved.headers["etag"] == '"3"'
        listing = api.client.get(
            f"/api/v1/procurement/requisitions?company_id={api.data.company_id}&status=APPROVED&cost_center_id={body['cost_center_id']}&page_size=1",
            headers=api.headers,
        )
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()["data"]] == [body["id"]]
        rejected = action(api, "requisitions", body["id"], "reject", approved.headers["etag"])
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"

        rejectable = create_requisition(api)
        rejectable_submitted = action(
            api, "requisitions", rejectable.json()["id"], "submit", rejectable.headers["etag"]
        )
        rejected_ok = action(
            api,
            "requisitions",
            rejectable.json()["id"],
            "reject",
            rejectable_submitted.headers["etag"],
        )
        assert rejected_ok.json()["status"] == "REJECTED"
        cancellable = create_requisition(api)
        cancelled = action(
            api, "requisitions", cancellable.json()["id"], "cancel", cancellable.headers["etag"]
        )
        assert cancelled.json()["status"] == "CANCELLED"


def test_purchase_order_full_issue_and_partial_total_receipt() -> None:
    with purchasing_api() as api:
        requisition = approve_requisition(api)
        supplier = create_supplier(api)
        created = create_order(api, requisition, supplier)
        order_id = created.json()["id"]
        submitted = action(api, "purchase-orders", order_id, "submit", created.headers["etag"])
        approved = action(api, "purchase-orders", order_id, "approve", submitted.headers["etag"])
        issued = action(api, "purchase-orders", order_id, "issue", approved.headers["etag"])
        item_id = issued.json()["items"][0]["id"]
        partial = action(
            api,
            "purchase-orders",
            order_id,
            "receive",
            issued.headers["etag"],
            {"items": [{"item_id": item_id, "quantity": "4"}]},
        )
        assert partial.status_code == 200
        assert partial.json()["status"] == "PARTIALLY_RECEIVED"
        completed = action(
            api,
            "purchase-orders",
            order_id,
            "receive",
            partial.headers["etag"],
            {"items": [{"item_id": item_id, "quantity": "6"}]},
        )
        assert completed.json()["status"] == "COMPLETED"
        assert completed.json()["items"][0]["outstanding_quantity"] == "0.000000"
        listing = api.client.get(
            f"/api/v1/procurement/purchase-orders?company_id={api.data.company_id}&supplier_id={supplier.json()['id']}&status=COMPLETED",
            headers=api.headers,
        )
        assert [item["id"] for item in listing.json()["data"]] == [order_id]


def test_purchase_order_cancel_and_business_validation() -> None:
    with purchasing_api() as api:
        draft_requisition = create_requisition(api)
        supplier = create_supplier(api)
        rejected = api.client.post(
            "/api/v1/procurement/purchase-orders",
            headers=api.headers,
            json={
                "company_id": str(api.data.company_id),
                "number": "PO-NOT-APPROVED",
                "source_requisition_id": draft_requisition.json()["id"],
                "supplier_id": supplier.json()["id"],
                "currency": "BRL",
                "payment_terms_code": "30D",
                "payment_terms_description": "Trinta dias",
                "installment_days": [30],
                "items": [
                    {
                        "requisition_item_id": draft_requisition.json()["items"][0]["id"],
                        "quantity": "1",
                        "unit_price": "1",
                    }
                ],
            },
        )
        assert rejected.status_code == 422
        approved = approve_requisition(api)
        created = create_order(api, approved, supplier)
        cancelled = action(
            api, "purchase-orders", created.json()["id"], "cancel", created.headers["etag"]
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"


def test_if_match_rbac_and_cross_tenant_are_fail_closed() -> None:
    with purchasing_api() as api:
        created = create_requisition(api)
        missing = api.client.post(
            f"/api/v1/procurement/requisitions/{created.json()['id']}/submit?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert missing.status_code == 428
        assert missing.json()["error"]["code"] == "PRECONDITION_REQUIRED"
        stale = action(api, "requisitions", created.json()["id"], "submit", '"9"')
        assert stale.status_code == 409
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            permissions=frozenset({PROCUREMENT_REQUISITION_READ, PROCUREMENT_ORDER_READ}),
        )
        assert (
            api.client.post(
                "/api/v1/procurement/requisitions", json=requisition_body(api), headers=api.headers
            ).status_code
            == 403
        )
        foreign = api.client.get(
            f"/api/v1/procurement/requisitions/{created.json()['id']}?company_id={api.data.other_company_id}",
            headers=api.headers,
        )
        assert foreign.status_code in {403, 404}


def test_invalid_period_and_service_unavailable_use_error_contract() -> None:
    with purchasing_api() as api:
        response = api.client.get(
            f"/api/v1/procurement/requisitions?company_id={api.data.company_id}&created_from=2026-10-03T10:00:00Z&created_to=2026-10-02T10:00:00Z",
            headers=api.headers,
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        app = cast(FastAPI, api.client.app)
        service = app.state.procurement_purchasing
        app.state.procurement_purchasing = None
        try:
            unavailable = api.client.get(
                f"/api/v1/procurement/requisitions?company_id={api.data.company_id}",
                headers=api.headers,
            )
            assert unavailable.status_code == 503
            assert unavailable.json()["error"]["code"] == "PROCUREMENT_PURCHASING_UNAVAILABLE"
        finally:
            app.state.procurement_purchasing = service
