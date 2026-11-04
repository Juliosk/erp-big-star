"""M12 Cash Flow REST API integration against real PostgreSQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.contracts import CompanyAccessService, PermissionCode
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.finance.application import (
    FINANCE_CASH_FLOW_PROJECT,
    FINANCE_CASH_FLOW_READ,
    FINANCE_CASH_FLOW_SCENARIO,
    CashFlowApplicationService,
    FinanceAuthorization,
)
from erp.modules.finance.infrastructure import PostgresCashFlowStore
from erp.modules.finance.infrastructure.cash_flow_alert_model import CashFlowAlertModel
from erp.modules.finance.infrastructure.cash_flow_model import (
    CashFlowAuditLogModel,
    CashFlowProjectionSnapshotModel,
    CashFlowScenarioDefinitionModel,
)
from erp.platform.audit.models import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.idempotency.models import IdempotencyRecordModel
from erp.platform.outbox.models import OutboxEventModel
from tests.integration.test_bank_statement_repository import bank_statement_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "cash-flow-test-token" else None


@contextmanager
def cash_flow_api() -> Iterator[tuple[TestClient, ProcurementFixture, ResolverStub]]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = bank_statement_fixture()
        data = client.portal.call(manager.__aenter__)
        authorization = FinanceAuthorization(
            CompanyAccessService(PostgresCorporateDirectory(data.database))
        )
        application = cast(FastAPI, client.app)
        application.state.finance_cash_flow = CashFlowApplicationService(
            PostgresCashFlowStore(
                data.database,
                ttl_seconds=get_settings().idempotency_ttl_seconds,
            ),
            authorization,
        )
        resolver.context = _context(data.actor_id, data.company_id)
        try:
            yield client, data, resolver
        finally:
            client.portal.call(_cleanup_cash_flow, data)
            client.portal.call(manager.__aexit__, None, None, None)


async def _cleanup_cash_flow(data: ProcurementFixture) -> None:
    async with data.database.session() as session, session.begin():
        alert_ids = tuple(
            await session.scalars(
                select(CashFlowAlertModel.id).where(
                    CashFlowAlertModel.company_id == data.company_id
                )
            )
        )
        if alert_ids:
            await session.execute(
                delete(AuditEventModel).where(
                    AuditEventModel.entity_type == "cash_flow_alert",
                    AuditEventModel.entity_id.in_(alert_ids),
                )
            )
            await session.execute(
                delete(OutboxEventModel).where(
                    OutboxEventModel.aggregate_type == "cash_flow_alert",
                    OutboxEventModel.aggregate_id.in_(alert_ids),
                )
            )
        await session.execute(
            text("SET LOCAL erp.allow_cash_flow_alert_cleanup = 'on'")
        )
        await session.execute(
            delete(CashFlowAlertModel).where(
                CashFlowAlertModel.company_id == data.company_id
            )
        )
        await session.execute(text("SET LOCAL erp.allow_cash_flow_cleanup = 'on'"))
        await session.execute(
            delete(CashFlowAuditLogModel).where(
                CashFlowAuditLogModel.company_id == data.company_id
            )
        )
        await session.execute(
            delete(CashFlowProjectionSnapshotModel).where(
                CashFlowProjectionSnapshotModel.company_id == data.company_id
            )
        )
        await session.execute(
            delete(CashFlowScenarioDefinitionModel).where(
                CashFlowScenarioDefinitionModel.company_id == data.company_id
            )
        )
        await session.execute(
            delete(IdempotencyRecordModel).where(
                IdempotencyRecordModel.scope.like(f"cash-flow:{data.company_id}:%")
            )
        )


def _context(
    actor_id: UUID,
    company_id: UUID,
    *,
    permissions: frozenset[PermissionCode] | None = None,
) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=permissions
        or frozenset(
            {
                FINANCE_CASH_FLOW_READ,
                FINANCE_CASH_FLOW_PROJECT,
                FINANCE_CASH_FLOW_SCENARIO,
            }
        ),
        scopes=frozenset({Scope(ScopeType.COMPANY, company_id)}),
    )


def _headers(**values: str) -> dict[str, str]:
    return {"Authorization": "Bearer cash-flow-test-token", **values}


def _projection_body(company_id: UUID, projection_id: UUID, scenario_id: UUID) -> dict[str, object]:
    return {
        "company_id": str(company_id),
        "projection_id": str(projection_id),
        "as_of": "2026-10-01",
        "horizon_end": "2026-12-30",
        "granularity": "MONTHLY",
        "minimum_reserve": "1000.00",
        "currency": "BRL",
        "scenario": {
            "id": str(scenario_id),
            "name": "Base API 192",
            "receivable_delay_days": 0,
            "cost_variation_rate": "0.0000",
            "business_day_convention": "FOLLOWING",
        },
    }


def _create(
    client: TestClient,
    data: ProcurementFixture,
    projection_id: UUID,
    scenario_id: UUID,
    *,
    key: str = "cash-flow-create-192",
) -> Any:
    return client.post(
        "/api/v1/finance/cash-flow/projections",
        headers=_headers(**{"Idempotency-Key": key}),
        json=_projection_body(data.company_id, projection_id, scenario_id),
    )


def test_create_replay_horizon_query_category_filter_and_tenant_isolation() -> None:
    with cash_flow_api() as (client, data, resolver):
        projection_id = uuid4()
        scenario_id = uuid4()
        created = _create(client, data, projection_id, scenario_id)
        assert created.status_code == 201, created.text
        assert created.headers["etag"] == '"1"'
        assert created.headers["idempotency-replayed"] == "false"
        assert created.json()["projection"]["horizon_kind"] == "SHORT_TERM"
        assert created.json()["projection"]["summary"]["liquidity_state"] == "INCOMPLETE"

        replay = _create(client, data, projection_id, scenario_id)
        assert replay.status_code == 200
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.json()["projection"]["id"] == str(projection_id)

        listing = client.get(
            "/api/v1/finance/cash-flow/horizons/SHORT_TERM",
            headers=_headers(),
            params={
                "company_id": str(data.company_id),
                "categories": "OPERATING",
            },
        )
        assert listing.status_code == 200, listing.text
        assert listing.json()["data"][0]["id"] == str(projection_id)
        assert listing.json()["data"][0]["selected_categories"] == ["OPERATING"]
        assert listing.json()["data"][0]["category_totals"]["committed_outflows"] == "0.00"

        detail = client.get(
            f"/api/v1/finance/cash-flow/projections/{projection_id}",
            headers=_headers(),
            params={"company_id": str(data.company_id)},
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"1"'

        resolver.context = _context(data.actor_id, data.other_company_id)
        hidden = client.get(
            f"/api/v1/finance/cash-flow/projections/{projection_id}",
            headers=_headers(),
            params={"company_id": str(data.other_company_id)},
        )
        assert hidden.status_code == 404


def test_refresh_requires_etag_is_concurrent_and_idempotent() -> None:
    with cash_flow_api() as (client, data, _):
        projection_id = uuid4()
        created = _create(client, data, projection_id, uuid4())
        assert created.status_code == 201, created.text
        url = f"/api/v1/finance/cash-flow/projections/{projection_id}/recalculate"
        params = {"company_id": str(data.company_id)}

        missing = client.post(
            url,
            headers=_headers(**{"Idempotency-Key": "refresh-missing-etag"}),
            params=params,
        )
        assert missing.status_code == 428
        assert missing.json()["error"]["code"] == "PRECONDITION_REQUIRED"

        refreshed = client.post(
            url,
            headers=_headers(
                **{"Idempotency-Key": "refresh-192", "If-Match": '"1"'}
            ),
            params=params,
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.headers["etag"] == '"2"'
        assert refreshed.json()["base_version"] == 1

        replay = client.post(
            url,
            headers=_headers(
                **{"Idempotency-Key": "refresh-192", "If-Match": '"1"'}
            ),
            params=params,
        )
        assert replay.status_code == 200
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.json()["projection"]["version"] == 2

        stale = client.post(
            url,
            headers=_headers(
                **{"Idempotency-Key": "refresh-stale-192", "If-Match": '"1"'}
            ),
            params=params,
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"


def test_stateless_scenario_is_replayable_and_does_not_persist_snapshot() -> None:
    with cash_flow_api() as (client, data, _):
        projection_id = uuid4()
        created = _create(client, data, projection_id, uuid4())
        assert created.status_code == 201, created.text
        request = {
            "company_id": str(data.company_id),
            "projection_id": str(projection_id),
            "scenario": {
                "id": str(uuid4()),
                "name": "Stress receivables and costs",
                "receivable_delay_days": 30,
                "cost_variation_rate": "0.1250",
                "business_day_convention": "FOLLOWING",
            },
        }
        headers = _headers(
            **{"Idempotency-Key": "scenario-192", "If-Match": '"1"'}
        )
        simulated = client.post(
            "/api/v1/finance/cash-flow/scenarios", headers=headers, json=request
        )
        assert simulated.status_code == 200, simulated.text
        assert simulated.headers["etag"] == '"1"'
        assert simulated.json()["persisted"] is False
        assert simulated.json()["projection"]["scenario"]["receivable_delay_days"] == 30

        replay = client.post(
            "/api/v1/finance/cash-flow/scenarios", headers=headers, json=request
        )
        assert replay.status_code == 200
        assert replay.headers["idempotency-replayed"] == "true"

        stored = client.get(
            f"/api/v1/finance/cash-flow/projections/{projection_id}",
            headers=_headers(),
            params={"company_id": str(data.company_id)},
        )
        assert stored.status_code == 200
        assert stored.json()["version"] == 1
        assert stored.json()["scenario"]["receivable_delay_days"] == 0


def test_cash_flow_rbac_and_validation_use_standard_error_contract() -> None:
    with cash_flow_api() as (client, data, resolver):
        resolver.context = _context(
            data.actor_id,
            data.company_id,
            permissions=frozenset({FINANCE_CASH_FLOW_READ}),
        )
        denied = _create(client, data, uuid4(), uuid4(), key="rbac-192")
        assert denied.status_code == 403

        resolver.context = _context(data.actor_id, data.company_id)
        invalid = _projection_body(data.company_id, uuid4(), uuid4())
        invalid["horizon_end"] = "2026-09-30"
        response = client.post(
            "/api/v1/finance/cash-flow/projections",
            headers=_headers(**{"Idempotency-Key": "invalid-192"}),
            json=invalid,
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
