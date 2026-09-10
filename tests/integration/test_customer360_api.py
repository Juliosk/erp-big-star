"""Customer 360 aggregates M14 data without leaking another company."""

from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.domain import Scope, ScopeType
from erp.modules.customer.application.permissions import (
    CUSTOMER_CREATE,
    CUSTOMER_MERGE,
    CUSTOMER_READ,
    CUSTOMER_UPDATE,
)
from erp.modules.customer.domain import (
    CustomerAddress,
    CustomerAddressRole,
    CustomerContact,
    CustomerContactKind,
    CustomerContactRole,
)
from erp.modules.customer.infrastructure.contact_address_repository import (
    CustomerContactAddressRepository,
)
from tests.integration.customer_api_support import CustomerApiFixture, customer_api
from tests.integration.test_customer_creation_api import creation_body

pytestmark = pytest.mark.integration


def allow_customer_360_flow(api: CustomerApiFixture) -> None:
    assert api.resolver.context is not None
    api.resolver.context = replace(
        api.resolver.context,
        permissions=frozenset({CUSTOMER_CREATE, CUSTOMER_READ, CUSTOMER_UPDATE, CUSTOMER_MERGE}),
    )


def create_customer(
    api: CustomerApiFixture,
    *,
    cpf: str,
    legal_name: str,
    trade_name: str | None = None,
) -> dict[str, Any]:
    response = api.client.post(
        "/api/v1/customers",
        json={**creation_body(api, cpf=cpf), "legal_name": legal_name, "trade_name": trade_name},
        headers={**api.headers, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json()["customer"])


def seed_contact_and_address(api: CustomerApiFixture, customer_id: UUID) -> None:
    async def seed() -> None:
        async with api.data.database.session() as session, session.begin():
            repository = CustomerContactAddressRepository(session, company_id=api.data.company_id)
            await repository.add_contact(
                CustomerContact.create(
                    company_id=api.data.company_id,
                    customer_id=customer_id,
                    role=CustomerContactRole.COMMERCIAL,
                    kind=CustomerContactKind.EMAIL,
                    value="Atendimento@Cliente.Com",
                    name="Atendimento",
                    is_primary=True,
                ),
                actor_id=api.data.actor_id,
            )
            await repository.add_address(
                CustomerAddress.create(
                    company_id=api.data.company_id,
                    customer_id=customer_id,
                    role=CustomerAddressRole.SHIPPING,
                    line1="Rua do Cliente, 100",
                    city="Sao Paulo",
                    state="SP",
                    postal_code="01234-567",
                    district="Centro",
                    is_primary=True,
                ),
                actor_id=api.data.actor_id,
            )

    assert api.client.portal is not None
    api.client.portal.call(seed)


def test_customer_360_returns_master_children_groups_and_merge_status() -> None:
    with customer_api() as api:
        allow_customer_360_flow(api)
        source = create_customer(
            api,
            cpf="52998224725",
            legal_name="Maria Souza",
            trade_name="Maria",
        )
        candidate = create_customer(
            api,
            cpf="15350946056",
            legal_name="Maria Sousa",
            trade_name="Maria S.",
        )
        seed_contact_and_address(api, UUID(source["id"]))
        group = api.client.post(
            "/api/v1/customer-groups",
            json={
                "company_id": str(api.data.company_id),
                "code": "vip360",
                "name": "Clientes 360",
                "description": "Segmento exibido no Customer 360",
            },
            headers=api.headers,
        )
        assert group.status_code == 201
        assignment = api.client.post(
            f"/api/v1/customers/{source['id']}/groups",
            json={
                "company_id": str(api.data.company_id),
                "customer_group_id": group.json()["id"],
            },
            headers=api.headers,
        )
        assert assignment.status_code == 201
        detection = api.client.post(
            f"/api/v1/customers/{source['id']}/duplicates/detect?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert detection.status_code == 200
        merge = api.client.post(
            f"/api/v1/customers/{source['id']}/merge-requests",
            json={
                "company_id": str(api.data.company_id),
                "candidate_customer_id": candidate["id"],
                "surviving_customer_id": source["id"],
                "reason": "Mesclagem fiscal pendente exibida no 360.",
            },
            headers=api.headers,
        )
        assert merge.status_code == 201

        result = api.client.get(
            f"/api/v1/customers/{source['id']}/360?company_id={api.data.company_id}",
            headers=api.headers,
        )

        assert result.status_code == 200
        assert result.headers["etag"] == '"1"'
        body = result.json()
        assert body["customer"]["legal_name"] == "Maria Souza"
        assert body["contacts"] == [
            {
                "id": body["contacts"][0]["id"],
                "company_id": str(api.data.company_id),
                "customer_id": source["id"],
                "role": "COMMERCIAL",
                "kind": "EMAIL",
                "value": "atendimento@cliente.com",
                "name": "Atendimento",
                "is_primary": True,
            }
        ]
        assert body["addresses"][0]["postal_code"] == "01234567"
        assert body["addresses"][0]["role"] == "SHIPPING"
        assert body["groups"] == [
            {
                "id": group.json()["id"],
                "code": "VIP360",
                "name": "Clientes 360",
                "active": True,
            }
        ]
        assert body["merge_status"]["duplicate_candidates"][0]["status"] == "MERGE_REQUESTED"
        assert (
            body["merge_status"]["duplicate_candidates"][0]["candidate_customer_id"]
            == candidate["id"]
        )
        assert body["merge_status"]["pending_merge_requests"] == [
            {
                "id": merge.json()["id"],
                "source_customer_id": source["id"],
                "candidate_customer_id": candidate["id"],
                "surviving_customer_id": source["id"],
                "status": "PENDING_APPROVAL",
                "version": 1,
            }
        ]


def test_customer_360_enforces_permission_and_company_scope() -> None:
    with customer_api() as api:
        allow_customer_360_flow(api)
        customer = create_customer(api, cpf="52998224725", legal_name="Maria Souza")
        assert api.resolver.context is not None
        api.resolver.context = replace(api.resolver.context, permissions=frozenset())
        denied = api.client.get(
            f"/api/v1/customers/{customer['id']}/360?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert denied.status_code == 403

        api.resolver.context = replace(
            api.resolver.context,
            permissions=frozenset({CUSTOMER_READ}),
            scopes=frozenset({Scope(ScopeType.COMPANY, api.data.other_company_id)}),
        )
        hidden = api.client.get(
            f"/api/v1/customers/{customer['id']}/360?company_id={api.data.other_company_id}",
            headers=api.headers,
        )
        assert hidden.status_code == 404
