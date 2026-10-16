"""M6 three-way matching API tests against real PostgreSQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Scope,
    ScopeType,
)
from erp.modules.fiscal.infrastructure import InboundFiscalDocumentItemModel
from erp.modules.procurement.application import (
    PROCUREMENT_MATCHING_EXECUTE,
    PROCUREMENT_MATCHING_READ,
)
from erp.modules.procurement.infrastructure import MatchingSessionModel
from erp.platform.config import get_settings
from erp.platform.idempotency import IdempotencyRecordModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_matching_repository import MatchingFixture, matching_fixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "matching-test-token" else None


@dataclass
class MatchingApiFixture:
    client: TestClient
    fixture: MatchingFixture
    resolver: ResolverStub

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer matching-test-token"}


@contextmanager
def matching_api() -> Iterator[MatchingApiFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = matching_fixture()
        fixture = client.portal.call(manager.__aenter__)
        data = fixture.data
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(
                data.actor_id,
                uuid4(),
                AuthenticationLevel.LEVEL_1,
            ),
            permissions=frozenset({PROCUREMENT_MATCHING_READ, PROCUREMENT_MATCHING_EXECUTE}),
            scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
        )
        try:
            yield MatchingApiFixture(client, fixture, resolver)
        finally:
            client.portal.call(_cleanup_api_records, fixture)
            client.portal.call(manager.__aexit__, None, None, None)


async def _cleanup_api_records(fixture: MatchingFixture) -> None:
    data = fixture.data
    async with data.database.session() as session, session.begin():
        matching_session_ids = tuple(
            await session.scalars(
                select(MatchingSessionModel.id).where(
                    MatchingSessionModel.company_id == data.company_id
                )
            )
        )
        await session.execute(
            delete(OutboxEventModel).where(
                OutboxEventModel.aggregate_type == "three_way_match_session",
                OutboxEventModel.aggregate_id.in_(matching_session_ids),
            )
        )
        await session.execute(
            delete(IdempotencyRecordModel).where(
                IdempotencyRecordModel.scope.like(f"procurement-matching:{data.company_id}:%")
            )
        )


def matching_body(api: MatchingApiFixture) -> dict[str, Any]:
    aggregate = api.fixture.aggregate
    purchase = aggregate.purchase_order_snapshot
    receiving = aggregate.receiving_fiscal_snapshot
    financial = aggregate.financial_snapshot
    return {
        "company_id": str(aggregate.company_id),
        "purchase_order_id": str(purchase.purchase_order.id),
        "goods_receipt_ids": [str(item.id) for item in receiving.goods_receipts],
        "inbound_fiscal_document_ids": [str(item.id) for item in receiving.fiscal_documents],
        "provisional_entry_id": str(financial.provisional_entry.id),
        "payable_id": None,
        "tolerance": {
            "unit_price_variance_percentage": "1",
            "quantity_variance_percentage": "1",
            "rounding_absolute_limit": "0.01",
            "version": 1,
        },
        "lines": [
            {
                "match_key": line.match_key,
                "purchase_order_item_id": str(line.purchase_order_item_id),
                "goods_receipt_item_id": str(line.goods_receipt_item_id),
                "fiscal_document_item_id": str(line.fiscal_document_item_id),
            }
            for line in aggregate.lines
        ],
    }


def create_session(api: MatchingApiFixture, key: str = "matching-create") -> Any:
    response = api.client.post(
        "/api/v1/procurement/matching-sessions",
        json=matching_body(api),
        headers={**api.headers, "Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    assert response.headers["etag"] == '"1"'
    return response


def test_matching_api_creates_executes_replays_and_exposes_explainable_detail() -> None:
    with matching_api() as api:
        created = create_session(api)
        replay = create_session(api)
        assert replay.json()["id"] == created.json()["id"]

        session_id = created.json()["id"]
        executed = api.client.post(
            f"/api/v1/procurement/matching-sessions/{session_id}/execute"
            f"?company_id={api.fixture.data.company_id}",
            headers={
                **api.headers,
                "If-Match": '"1"',
                "Idempotency-Key": "matching-execute",
            },
        )
        assert executed.status_code == 200, executed.text
        assert executed.headers["etag"] == '"3"'
        assert executed.json()["session"]["status"] == "MATCHED"
        assert len(executed.json()["event_ids"]) == 1
        assert executed.json()["session"]["lines"][0]["result_status"] == "MATCHED"

        execution_replay = api.client.post(
            f"/api/v1/procurement/matching-sessions/{session_id}/execute"
            f"?company_id={api.fixture.data.company_id}",
            headers={
                **api.headers,
                "If-Match": '"1"',
                "Idempotency-Key": "matching-execute",
            },
        )
        assert execution_replay.status_code == 200
        assert execution_replay.json() == executed.json(), _response_differences(
            execution_replay.json(), executed.json()
        )

        detail = api.client.get(
            f"/api/v1/procurement/matching-sessions/{session_id}"
            f"?company_id={api.fixture.data.company_id}",
            headers=api.headers,
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"3"'
        assert [item["to_status"] for item in detail.json()["audit_history"]] == [
            "PENDING",
            "RUNNING",
            "MATCHED",
        ]
        assert detail.json()["session"]["snapshot"]["purchase_order"]["version"] >= 1

        listing = api.client.get(
            "/api/v1/procurement/matching-sessions",
            params={
                "company_id": str(api.fixture.data.company_id),
                "status": "MATCHED",
                "purchase_order_id": matching_body(api)["purchase_order_id"],
                "page": 1,
                "page_size": 1,
            },
            headers=api.headers,
        )
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()["data"]] == [session_id]
        assert listing.json()["meta"] == {
            "page": 1,
            "page_size": 1,
            "has_more": False,
        }


def test_matching_api_exposes_only_discrepancies_in_exception_queue() -> None:
    with matching_api() as api:
        fiscal_item_id = api.fixture.aggregate.lines[0].fiscal_document_item_id

        async def change_price() -> None:
            async with api.fixture.data.database.session() as session, session.begin():
                await session.execute(
                    update(InboundFiscalDocumentItemModel)
                    .where(InboundFiscalDocumentItemModel.id == fiscal_item_id)
                    .values(unit_price="99.00", total_amount="990.00")
                )

        assert api.client.portal is not None
        api.client.portal.call(change_price)
        created = create_session(api, "matching-discrepancy-create")
        executed = api.client.post(
            f"/api/v1/procurement/matching-sessions/{created.json()['id']}/execute",
            params={"company_id": str(api.fixture.data.company_id)},
            headers={
                **api.headers,
                "If-Match": '"1"',
                "Idempotency-Key": "matching-discrepancy-execute",
            },
        )
        assert executed.status_code == 200
        assert executed.json()["session"]["status"] == "DISCREPANCY_DETECTED"
        line = executed.json()["session"]["lines"][0]
        assert line["result_status"] == "PRICE_MISMATCH"
        assert line["unit_price_delta"] != "0.000000"
        assert line["reasons"] == ["UNIT_PRICE_TOLERANCE_EXCEEDED"]

        queue = api.client.get(
            "/api/v1/procurement/matching-sessions/exceptions",
            params={"company_id": str(api.fixture.data.company_id)},
            headers=api.headers,
        )
        assert queue.status_code == 200
        assert [item["id"] for item in queue.json()["data"]] == [created.json()["id"]]


def test_matching_api_enforces_preconditions_rbac_and_cross_tenant_isolation() -> None:
    with matching_api() as api:
        created = create_session(api, "matching-guards-create")
        session_id = created.json()["id"]
        endpoint = (
            f"/api/v1/procurement/matching-sessions/{session_id}/execute"
            f"?company_id={api.fixture.data.company_id}"
        )
        missing_precondition = api.client.post(
            endpoint,
            headers={**api.headers, "Idempotency-Key": "matching-missing-etag"},
        )
        assert missing_precondition.status_code == 428
        assert missing_precondition.json()["error"]["code"] == "PRECONDITION_REQUIRED"

        stale = api.client.post(
            endpoint,
            headers={
                **api.headers,
                "If-Match": '"99"',
                "Idempotency-Key": "matching-stale-etag",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"

        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            permissions=frozenset({PROCUREMENT_MATCHING_READ}),
        )
        forbidden = api.client.post(
            endpoint,
            headers={
                **api.headers,
                "If-Match": '"1"',
                "Idempotency-Key": "matching-forbidden",
            },
        )
        assert forbidden.status_code == 403

        api.resolver.context = replace(
            api.resolver.context,
            permissions=frozenset(),
        )
        forbidden_read = api.client.get(
            f"/api/v1/procurement/matching-sessions/{session_id}",
            params={"company_id": str(api.fixture.data.company_id)},
            headers=api.headers,
        )
        assert forbidden_read.status_code == 403

        api.resolver.context = replace(
            api.resolver.context,
            permissions=frozenset({PROCUREMENT_MATCHING_READ}),
            scopes=frozenset({Scope(ScopeType.COMPANY, api.fixture.data.other_company_id)}),
        )
        hidden = api.client.get(
            f"/api/v1/procurement/matching-sessions/{session_id}",
            params={"company_id": str(api.fixture.data.other_company_id)},
            headers=api.headers,
        )
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_matching_api_requires_idempotency_key_and_rejects_payload_drift() -> None:
    with matching_api() as api:
        missing = api.client.post(
            "/api/v1/procurement/matching-sessions",
            json=matching_body(api),
            headers=api.headers,
        )
        assert missing.status_code == 400
        assert missing.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"

        create_session(api, "matching-payload-drift")
        changed = matching_body(api)
        changed["tolerance"]["quantity_variance_percentage"] = "2"
        conflict = api.client.post(
            "/api/v1/procurement/matching-sessions",
            json=changed,
            headers={**api.headers, "Idempotency-Key": "matching-payload-drift"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"


def _response_differences(left: object, right: object, path: str = "$") -> list[object]:
    if isinstance(left, dict) and isinstance(right, dict):
        return [
            difference
            for key in left.keys() | right.keys()
            for difference in _response_differences(left.get(key), right.get(key), f"{path}.{key}")
        ]
    if isinstance(left, list) and isinstance(right, list):
        return [
            difference
            for index, (left_item, right_item) in enumerate(zip(left, right, strict=False))
            for difference in _response_differences(left_item, right_item, f"{path}[{index}]")
        ]
    return [] if left == right else [(path, left, right)]
