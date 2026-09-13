"""M14 customer groups are company-scoped and auditable."""

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
from erp.modules.customer.infrastructure import CustomerGroupMemberModel, CustomerGroupModel
from erp.platform.audit import AuditEventModel, AuditService
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.customer_api_support import CustomerApiFixture, customer_api
from tests.integration.test_customer_creation_api import allow_create, creation_body

pytestmark = pytest.mark.integration


def allow_group_write(api: CustomerApiFixture) -> None:
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
    allow_group_write(api)
    return cast(dict[str, Any], response.json()["customer"])


def group_counts(api: CustomerApiFixture, *, customer_id: UUID) -> tuple[int, int, int, int]:
    async def query() -> tuple[int, int, int, int]:
        async with api.data.database.session() as session:
            groups = await session.scalar(
                select(func.count())
                .select_from(CustomerGroupModel)
                .where(CustomerGroupModel.company_id == api.data.company_id)
            )
            members = await session.scalar(
                select(func.count())
                .select_from(CustomerGroupMemberModel)
                .where(CustomerGroupMemberModel.company_id == api.data.company_id)
            )
            audit = await session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(
                    AuditEventModel.company_id == api.data.company_id,
                    AuditEventModel.module == "crm",
                    AuditEventModel.operation == "CustomerGroupChanged",
                )
            )
            outbox = await session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(
                    OutboxEventModel.source_module == "crm",
                    OutboxEventModel.event_type == "CustomerGroupChanged",
                    OutboxEventModel.aggregate_id == customer_id,
                )
            )
            return groups or 0, members or 0, audit or 0, outbox or 0

    assert api.client.portal is not None
    return cast(tuple[int, int, int, int], api.client.portal.call(query))


def test_create_list_and_assign_customer_group_emits_effects() -> None:
    with customer_api() as api:
        customer = create_customer(api)
        group_response = api.client.post(
            "/api/v1/customer-groups",
            json={
                "company_id": str(api.data.company_id),
                "code": "vip",
                "name": "Clientes VIP",
                "description": "Segmentacao comercial",
            },
            headers=api.headers,
        )
        assert group_response.status_code == 201
        assert group_response.headers["etag"] == '"1"'
        group = group_response.json()
        assert group["code"] == "VIP"
        assert group["name"] == "Clientes VIP"
        listed = api.client.get(
            f"/api/v1/customer-groups?company_id={api.data.company_id}&active=true",
            headers=api.headers,
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["data"]] == [group["id"]]

        correlation_id, request_id = uuid4(), uuid4()
        assignment = api.client.post(
            f"/api/v1/customers/{customer['id']}/groups",
            json={"company_id": str(api.data.company_id), "customer_group_id": group["id"]},
            headers={
                **api.headers,
                "X-Correlation-ID": str(correlation_id),
                "X-Request-ID": str(request_id),
            },
        )
        assert assignment.status_code == 201
        body = assignment.json()
        assert body["customer_id"] == customer["id"]
        assert body["customer_group_id"] == group["id"]
        assert group_counts(api, customer_id=UUID(customer["id"])) == (1, 1, 1, 1)

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
                assert envelope.message_type == "CustomerGroupChanged"
                assert envelope.payload == {
                    "customer_id": customer["id"],
                    "customer_group_id": group["id"],
                }
                assert envelope.aggregate_id == UUID(customer["id"])
                assert envelope.correlation_id == audit.correlation_id == correlation_id
                assert envelope.request_id == audit.request_id == request_id

        assert api.client.portal is not None
        api.client.portal.call(verify)


def test_group_api_enforces_permission_scope_duplicate_and_validation() -> None:
    with customer_api() as api:
        assert (
            api.client.post(
                "/api/v1/customer-groups",
                json={"company_id": str(api.data.company_id), "code": "VIP", "name": "VIP"},
                headers=api.headers,
            ).status_code
            == 403
        )
        allow_group_write(api)
        assert (
            api.client.post(
                "/api/v1/customer-groups",
                json={"company_id": str(api.data.other_company_id), "code": "VIP", "name": "VIP"},
                headers=api.headers,
            ).status_code
            == 404
        )
        first = api.client.post(
            "/api/v1/customer-groups",
            json={"company_id": str(api.data.company_id), "code": "VIP", "name": "VIP"},
            headers=api.headers,
        )
        duplicate = api.client.post(
            "/api/v1/customer-groups",
            json={"company_id": str(api.data.company_id), "code": "vip", "name": "VIP 2"},
            headers=api.headers,
        )
        invalid = api.client.post(
            "/api/v1/customer-groups",
            json={"company_id": str(api.data.company_id), "code": "x", "name": "VIP"},
            headers=api.headers,
        )
        assert first.status_code == 201
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "CUSTOMER_GROUP_CONFLICT"
        assert invalid.status_code == 422


@pytest.mark.parametrize(
    ("component", "method"), [(AuditService, "record"), (OutboxService, "enqueue")]
)
def test_failed_group_assignment_effect_rolls_back_membership(
    monkeypatch: pytest.MonkeyPatch, component: type[Any], method: str
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Forced group effect failure")

    with customer_api() as api:
        customer = create_customer(api)
        group = api.client.post(
            "/api/v1/customer-groups",
            json={"company_id": str(api.data.company_id), "code": "VIP", "name": "VIP"},
            headers=api.headers,
        ).json()
        with monkeypatch.context() as patch:
            patch.setattr(component, method, fail)
            with pytest.raises(RuntimeError, match="Forced group effect failure"):
                api.client.post(
                    f"/api/v1/customers/{customer['id']}/groups",
                    json={"company_id": str(api.data.company_id), "customer_group_id": group["id"]},
                    headers=api.headers,
                )
        assert group_counts(api, customer_id=UUID(customer["id"])) == (1, 0, 0, 0)
