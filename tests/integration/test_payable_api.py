"""M12 payable REST API integration against real PostgreSQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.finance.application import (
    FINANCE_PAYABLE_ADJUST,
    FINANCE_PAYABLE_CREATE,
    FINANCE_PAYABLE_READ,
    FinanceAuthorization,
    PayableApplicationService,
    PayableCommandMetadata,
)
from erp.modules.finance.domain import FinanceVersionConflictError, PayableSegregationPolicy
from erp.modules.finance.infrastructure import (
    PayableRepository,
    PostgresPayableStore,
    ProvisionalEntryRepository,
)
from erp.modules.finance.infrastructure.payable_store import _replay
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyRecordModel
from tests.integration.test_payable_repository import _payable, _provision, finance_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "finance-test-token" else None


@contextmanager
def payable_api() -> Iterator[tuple[TestClient, ProcurementFixture, ResolverStub]]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = finance_fixture()
        data = client.portal.call(manager.__aenter__)
        application = cast(FastAPI, client.app)
        application.state.finance_payables = PayableApplicationService(
            PostgresPayableStore(data.database, ttl_seconds=3600),
            FinanceAuthorization(CompanyAccessService(PostgresCorporateDirectory(data.database))),
        )
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset(
                {FINANCE_PAYABLE_READ, FINANCE_PAYABLE_CREATE, FINANCE_PAYABLE_ADJUST}
            ),
            scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
        )
        try:
            yield client, data, resolver
        finally:

            async def cleanup() -> None:
                async with data.database.session() as session, session.begin():
                    await session.execute(
                        delete(AuditEventModel).where(
                            AuditEventModel.company_id.in_(
                                (data.company_id, data.other_company_id)
                            ),
                            AuditEventModel.module == "finance",
                        )
                    )
                    await session.execute(
                        delete(IdempotencyRecordModel).where(
                            IdempotencyRecordModel.scope.like(
                                f"finance-payable:{data.company_id}:%"
                            )
                        )
                    )

            client.portal.call(cleanup)
            client.portal.call(manager.__aexit__, None, None, None)


def _headers(**values: str) -> dict[str, str]:
    return {"Authorization": "Bearer finance-test-token", **values}


def _body(data: ProcurementFixture, *, number: str | None = None) -> dict[str, Any]:
    return {
        "company_id": str(data.company_id),
        "number": number or f"AP-{uuid4().hex[:10]}",
        "supplier_id": str(uuid4()),
        "supplier_tax_id": "12345678000195",
        "currency": "BRL",
        "nominal_amount": "100.00",
        "installments": [
            {"due_date": "2026-11-10", "amount": "40.00"},
            {"due_date": "2026-12-10", "amount": "60.00"},
        ],
    }


def _create(client: TestClient, data: ProcurementFixture, *, key: str | None = None) -> Any:
    return client.post(
        "/api/v1/finance/payables",
        headers=_headers(**{"Idempotency-Key": key or str(uuid4())}),
        json=_body(data),
    )


def test_create_adjust_submit_query_filters_and_audit_history() -> None:
    with payable_api() as (client, data, _):
        key = str(uuid4())
        body = _body(data)
        created = client.post(
            "/api/v1/finance/payables",
            headers=_headers(**{"Idempotency-Key": key}),
            json=body,
        )
        assert created.status_code == 201, created.text
        assert created.headers["etag"] == '"1"'
        assert created.headers["idempotency-replayed"] == "false"
        replay = client.post(
            "/api/v1/finance/payables",
            headers=_headers(**{"Idempotency-Key": key}),
            json=body,
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == created.json()["id"]
        assert replay.headers["idempotency-replayed"] == "true"

        payable_id = created.json()["id"]
        adjusted = client.patch(
            f"/api/v1/finance/payables/{payable_id}/adjustments?company_id={data.company_id}",
            headers=_headers(**{"If-Match": created.headers["etag"]}),
            json={"discount_amount": "5.00", "surcharge_amount": "10.00"},
        )
        assert adjusted.status_code == 200, adjusted.text
        assert adjusted.headers["etag"] == '"2"'
        assert adjusted.json()["total_amount"] == "105.00"
        assert adjusted.json()["installments"][-1]["amount"] == "65.00"

        listing = client.get(
            "/api/v1/finance/payables",
            headers=_headers(),
            params={
                "company_id": str(data.company_id),
                "supplier_id": body["supplier_id"],
                "status": "DRAFT",
                "due_from": "2026-12-01",
                "due_to": "2026-12-31",
                "created_from": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                "created_to": (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
                "page_size": 1,
            },
        )
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()["data"]] == [payable_id]
        assert (
            client.get(
                "/api/v1/finance/payables",
                headers=_headers(),
                params={"company_id": str(data.company_id), "due_from": "2026-12-01"},
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/v1/finance/payables",
                headers=_headers(),
                params={"company_id": str(data.company_id), "due_to": "2026-11-30"},
            ).status_code
            == 200
        )

        detail = client.get(
            f"/api/v1/finance/payables/{payable_id}?company_id={data.company_id}",
            headers=_headers(),
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"2"'
        assert detail.json()["provisional_entry"] is None
        assert [item["operation"] for item in detail.json()["audit_history"]] == [
            "PAYABLE_CREATED",
            "PAYABLE_ADJUSTED",
        ]

        submitted = client.post(
            f"/api/v1/finance/payables/{payable_id}/submit-for-approval"
            f"?company_id={data.company_id}",
            headers=_headers(**{"If-Match": detail.headers["etag"]}),
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "PENDING_APPROVAL"
        assert submitted.headers["etag"] == '"3"'
        invalid_transition = client.post(
            f"/api/v1/finance/payables/{payable_id}/submit-for-approval"
            f"?company_id={data.company_id}",
            headers=_headers(**{"If-Match": submitted.headers["etag"]}),
        )
        assert invalid_transition.status_code == 422
        assert invalid_transition.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"


def test_schedule_is_idempotent_and_rejects_stale_or_changed_payload() -> None:
    with payable_api() as (client, data, _):
        created = _create(client, data)
        payable_id = UUID(created.json()["id"])

        async def approve() -> None:
            async with data.database.session() as session, session.begin():
                repository = PayableRepository(session, company_id=data.company_id)
                current = await repository.get(payable_id)
                assert current is not None
                pending = current.submit_for_approval()
                await repository.save(pending, actor_id=data.actor_id, expected_version=1)
                approved = pending.approve(
                    approver_id=uuid4(),
                    policy=PayableSegregationPolicy(Decimal("100.00")),
                )
                await repository.save(approved, actor_id=data.actor_id, expected_version=2)

        assert client.portal is not None
        client.portal.call(approve)
        key = str(uuid4())
        schedule_ids = [str(uuid4()), str(uuid4())]
        url = f"/api/v1/finance/payables/{payable_id}/schedule?company_id={data.company_id}"
        scheduled = client.post(
            url,
            headers=_headers(**{"If-Match": '"3"', "Idempotency-Key": key}),
            json={"schedule_ids": schedule_ids},
        )
        assert scheduled.status_code == 200, scheduled.text
        assert scheduled.json()["status"] == "SCHEDULED"
        assert scheduled.headers["etag"] == '"4"'
        replay = client.post(
            url,
            headers=_headers(**{"If-Match": '"3"', "Idempotency-Key": key}),
            json={"schedule_ids": schedule_ids},
        )
        assert replay.status_code == 200
        assert replay.headers["idempotency-replayed"] == "true"
        conflict = client.post(
            url,
            headers=_headers(**{"If-Match": '"3"', "Idempotency-Key": key}),
            json={"schedule_ids": [str(uuid4()), str(uuid4())]},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == ("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD")

        invalid_schedule = _create(client, data)
        invalid_id = UUID(invalid_schedule.json()["id"])

        async def approve_invalid_schedule() -> None:
            async with data.database.session() as session, session.begin():
                repository = PayableRepository(session, company_id=data.company_id)
                current = await repository.get(invalid_id)
                assert current is not None
                pending = current.submit_for_approval()
                await repository.save(pending, actor_id=data.actor_id)
                await repository.save(
                    pending.approve(
                        approver_id=uuid4(),
                        policy=PayableSegregationPolicy(Decimal("100.00")),
                    ),
                    actor_id=data.actor_id,
                )

        client.portal.call(approve_invalid_schedule)
        invalid = client.post(
            f"/api/v1/finance/payables/{invalid_id}/schedule?company_id={data.company_id}",
            headers=_headers(**{"If-Match": '"3"', "Idempotency-Key": str(uuid4())}),
            json={"schedule_ids": [str(uuid4())]},
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"


def test_etag_rbac_tenant_scope_and_validation_fail_closed() -> None:
    with payable_api() as (client, data, resolver):
        created = _create(client, data)
        payable_id = created.json()["id"]
        missing = client.post(
            f"/api/v1/finance/payables/{payable_id}/submit-for-approval"
            f"?company_id={data.company_id}",
            headers=_headers(),
        )
        assert missing.status_code == 428
        assert missing.json()["error"]["code"] == "PRECONDITION_REQUIRED"
        malformed = client.post(
            f"/api/v1/finance/payables/{payable_id}/submit-for-approval"
            f"?company_id={data.company_id}",
            headers=_headers(**{"If-Match": "1"}),
        )
        assert malformed.status_code == 400
        assert malformed.json()["error"]["code"] == "INVALID_IF_MATCH"
        stale = client.patch(
            f"/api/v1/finance/payables/{payable_id}/adjustments?company_id={data.company_id}",
            headers=_headers(**{"If-Match": '"9"'}),
            json={"discount_amount": "0.00", "surcharge_amount": "0.00"},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
        foreign = client.get(
            f"/api/v1/finance/payables/{payable_id}?company_id={data.other_company_id}",
            headers=_headers(),
        )
        assert foreign.status_code == 404
        assert foreign.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
        absent = client.get(
            f"/api/v1/finance/payables/{uuid4()}?company_id={data.company_id}",
            headers=_headers(),
        )
        assert absent.status_code == 404

        invalid_period = client.get(
            "/api/v1/finance/payables",
            headers=_headers(),
            params={
                "company_id": str(data.company_id),
                "due_from": date(2026, 12, 2).isoformat(),
                "due_to": date(2026, 12, 1).isoformat(),
            },
        )
        assert invalid_period.status_code == 422
        assert invalid_period.json()["error"]["code"] == "VALIDATION_ERROR"
        invalid_created_period = client.get(
            "/api/v1/finance/payables",
            headers=_headers(),
            params={
                "company_id": str(data.company_id),
                "created_from": "2026-12-02T00:00:00Z",
                "created_to": "2026-12-01T00:00:00Z",
            },
        )
        assert invalid_created_period.status_code == 422

        invalid_draft = _body(data)
        invalid_draft["installments"] = [{"due_date": "2026-11-10", "amount": "99.00"}]
        rejected = client.post(
            "/api/v1/finance/payables",
            headers=_headers(**{"Idempotency-Key": str(uuid4())}),
            json=invalid_draft,
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"

        duplicate_body = _body(data)
        first = client.post(
            "/api/v1/finance/payables",
            headers=_headers(**{"Idempotency-Key": str(uuid4())}),
            json=duplicate_body,
        )
        assert first.status_code == 201
        duplicate = client.post(
            "/api/v1/finance/payables",
            headers=_headers(**{"Idempotency-Key": str(uuid4())}),
            json=duplicate_body,
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "PAYABLE_CONFLICT"

        assert resolver.context is not None
        resolver.context = replace(
            resolver.context,
            permissions=frozenset({FINANCE_PAYABLE_READ}),
        )
        denied = _create(client, data)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PERMISSION_FORBIDDEN"

        application = cast(FastAPI, client.app)
        service = application.state.finance_payables
        application.state.finance_payables = None
        try:
            unavailable = client.get(
                f"/api/v1/finance/payables?company_id={data.company_id}",
                headers=_headers(),
            )
            assert unavailable.status_code == 503
            assert unavailable.json()["error"]["code"] == "FINANCE_PAYABLE_UNAVAILABLE"
        finally:
            application.state.finance_payables = service


def test_authentication_source_provision_and_application_guards() -> None:
    with payable_api() as (client, data, resolver):
        no_token = client.get(f"/api/v1/finance/payables?company_id={data.company_id}")
        assert no_token.status_code == 401
        invalid_token = client.get(
            f"/api/v1/finance/payables?company_id={data.company_id}",
            headers={"Authorization": "Bearer invalid"},
        )
        assert invalid_token.status_code == 401

        application = cast(FastAPI, client.app)
        security = application.state.security_context_resolver
        application.state.security_context_resolver = None
        try:
            unavailable = client.get(
                f"/api/v1/finance/payables?company_id={data.company_id}",
                headers=_headers(),
            )
            assert unavailable.status_code == 503
            assert unavailable.json()["error"]["code"] == "AUTHENTICATION_UNAVAILABLE"
        finally:
            application.state.security_context_resolver = security

        provision = _provision(data)
        title = _payable(data, provisional_entry_id=provision.id)

        async def seed_and_validate_guards() -> None:
            async with data.database.session() as session, session.begin():
                await ProvisionalEntryRepository(session, company_id=data.company_id).add(
                    provision, actor_id=data.actor_id
                )
                await PayableRepository(session, company_id=data.company_id).add(
                    title, actor_id=data.actor_id
                )
            service = cast(PayableApplicationService, application.state.finance_payables)
            assert resolver.context is not None
            with pytest.raises(ApplicationError, match="Invalid pagination"):
                await service.list(
                    resolver.context,
                    data.company_id,
                    page=0,
                    page_size=50,
                )

        assert client.portal is not None
        client.portal.call(seed_and_validate_guards)
        detail = client.get(
            f"/api/v1/finance/payables/{title.id}?company_id={data.company_id}",
            headers=_headers(),
        )
        assert detail.status_code == 200
        assert detail.json()["provisional_entry"]["id"] == str(provision.id)
        assert detail.json()["provisional_entry"]["source_id"] == str(provision.source_id)
        assert PayableCommandMetadata.new().request_id.int != 0


def test_adapter_translates_repository_races_and_corrupted_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with payable_api() as (client, data, _):
        draft = _create(client, data)
        approved_source = _create(client, data)
        approved_id = UUID(approved_source.json()["id"])

        async def approve() -> None:
            async with data.database.session() as session, session.begin():
                repository = PayableRepository(session, company_id=data.company_id)
                current = await repository.get(approved_id)
                assert current is not None
                pending = current.submit_for_approval()
                await repository.save(pending, actor_id=data.actor_id)
                await repository.save(
                    pending.approve(
                        approver_id=uuid4(),
                        policy=PayableSegregationPolicy(Decimal("100.00")),
                    ),
                    actor_id=data.actor_id,
                )

        assert client.portal is not None
        client.portal.call(approve)

        async def stale(*_: object, **__: object) -> None:
            raise FinanceVersionConflictError("concurrent winner")

        monkeypatch.setattr(PayableRepository, "save", stale)
        adjusted = client.patch(
            f"/api/v1/finance/payables/{draft.json()['id']}/adjustments"
            f"?company_id={data.company_id}",
            headers=_headers(**{"If-Match": '"1"'}),
            json={"discount_amount": "0.00", "surcharge_amount": "1.00"},
        )
        assert adjusted.status_code == 409
        scheduled = client.post(
            f"/api/v1/finance/payables/{approved_id}/schedule?company_id={data.company_id}",
            headers=_headers(**{"If-Match": '"3"', "Idempotency-Key": str(uuid4())}),
            json={"schedule_ids": [str(uuid4()), str(uuid4())]},
        )
        assert scheduled.status_code == 409
        missing = client.post(
            f"/api/v1/finance/payables/{uuid4()}/submit-for-approval?company_id={data.company_id}",
            headers=_headers(**{"If-Match": '"1"'}),
        )
        assert missing.status_code == 404

        async def corrupted_replay() -> None:
            async with data.database.session() as session:
                with pytest.raises(RuntimeError, match="no payable identity"):
                    await _replay(session, data.company_id, None)

        client.portal.call(corrupted_replay)
