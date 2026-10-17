"""M12 Treasury REST API integration against real PostgreSQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from erp.apps.api.app import create_app
from erp.apps.api.treasury_candidates import PostgresTreasuryPaymentCandidateProvider
from erp.apps.api.treasury_execution import M22PaymentBatchApprovalGateway
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.finance.application import (
    FINANCE_TREASURY_BATCH_APPROVE,
    FINANCE_TREASURY_BATCH_CREATE,
    FINANCE_TREASURY_BATCH_EXECUTE,
    FINANCE_TREASURY_READ,
    FinanceAuthorization,
    TreasuryApplicationService,
    TreasuryQueryService,
)
from erp.modules.finance.infrastructure import PostgresTreasuryStore
from erp.modules.procurement.infrastructure import MatchingSessionModel
from erp.modules.workflow.application.decisions import CommandMetadata, DecideWorkflowInstance
from erp.modules.workflow.domain import ApprovalDecisionKind
from erp.modules.workflow.infrastructure import (
    WorkflowRepository,
    apply_workflow_decision,
)
from erp.platform.config import get_settings
from erp.platform.idempotency import IdempotencyRecordModel
from tests.integration.test_payment_batch_execution import (
    _add_payment_workflow,
    _cleanup_workflow_and_events,
)
from tests.integration.test_treasury_repository import TreasuryFixture, treasury_fixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "treasury-test-token" else None


@contextmanager
def treasury_api() -> Iterator[tuple[TestClient, TreasuryFixture, ResolverStub]]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = treasury_fixture()
        fixture = client.portal.call(manager.__aenter__)
        data = fixture.matching.data

        async def prepare() -> None:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    update(MatchingSessionModel)
                    .where(
                        MatchingSessionModel.company_id == data.company_id,
                        MatchingSessionModel.id == fixture.matching.aggregate.id,
                    )
                    .values(payable_id=fixture.batch.items[0].payable_id)
                )
                await _add_payment_workflow(session, data.company_id, data.actor_id)

        client.portal.call(prepare)
        authorization = FinanceAuthorization(
            CompanyAccessService(PostgresCorporateDirectory(data.database))
        )
        store = PostgresTreasuryStore(
            data.database,
            ttl_seconds=3600,
            approval_gateway_factory=M22PaymentBatchApprovalGateway,
            candidate_provider_factory=PostgresTreasuryPaymentCandidateProvider,
        )
        application = cast(FastAPI, client.app)
        application.state.finance_treasury = TreasuryApplicationService(store, authorization)
        application.state.finance_treasury_queries = TreasuryQueryService(store, authorization)
        resolver.context = _context(data.actor_id, data.company_id)
        try:
            yield client, fixture, resolver
        finally:

            async def cleanup() -> None:
                async with data.database.session() as session, session.begin():
                    await session.execute(
                        delete(IdempotencyRecordModel).where(
                            IdempotencyRecordModel.scope.like(
                                f"finance-treasury:{data.company_id}:%"
                            )
                        )
                    )
                    await _cleanup_workflow_and_events(
                        session,
                        data.company_id,
                        UUID(created_batch_id)
                        if (created_batch_id := getattr(application.state, "test_batch_id", None))
                        else fixture.batch.id,
                    )
                    await session.execute(
                        update(MatchingSessionModel)
                        .where(
                            MatchingSessionModel.company_id == data.company_id,
                            MatchingSessionModel.id == fixture.matching.aggregate.id,
                        )
                        .values(payable_id=None)
                    )

            client.portal.call(cleanup)
            client.portal.call(manager.__aexit__, None, None, None)


def _context(actor_id: UUID, company_id: UUID) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=frozenset(
            {
                FINANCE_TREASURY_READ,
                FINANCE_TREASURY_BATCH_CREATE,
                FINANCE_TREASURY_BATCH_APPROVE,
                FINANCE_TREASURY_BATCH_EXECUTE,
            }
        ),
        scopes=frozenset({Scope(ScopeType.COMPANY, company_id)}),
    )


def _headers(**values: str) -> dict[str, str]:
    return {"Authorization": "Bearer treasury-test-token", **values}


def _body(fixture: TreasuryFixture, *, code: str | None = None) -> dict[str, Any]:
    data = fixture.matching.data
    item = fixture.batch.items[0]
    beneficiary = item.beneficiary
    return {
        "company_id": str(data.company_id),
        "code": code or f"API-{uuid4().hex[:10].upper()}",
        "treasury_account_id": str(fixture.batch.treasury_account_id),
        "scheduled_date": fixture.batch.scheduled_date.isoformat(),
        "remittance_format": "CNAB_240",
        "execution_mode": "PRODUCTION",
        "installments": [
            {
                "installment_id": str(item.installment_id),
                "beneficiary": {
                    "bank_code": beneficiary.bank_code,
                    "branch_number": beneficiary.branch_number,
                    "account_number": beneficiary.account_number,
                    "account_digit": beneficiary.account_digit,
                    "account_type": beneficiary.account_type.value,
                    "holder_name": beneficiary.holder_name,
                    "holder_tax_id": beneficiary.holder_tax_id,
                },
            }
        ],
    }


def _create(client: TestClient, fixture: TreasuryFixture, *, key: str | None = None) -> Any:
    response = client.post(
        "/api/v1/finance/treasury/batches",
        headers=_headers(**{"Idempotency-Key": key or str(uuid4())}),
        json=_body(fixture),
    )
    if response.status_code == 201:
        cast(FastAPI, client.app).state.test_batch_id = response.json()["batch"]["id"]
    return response


def test_create_replay_list_detail_and_dry_run() -> None:
    with treasury_api() as (client, fixture, _):
        data = fixture.matching.data
        key = str(uuid4())
        body = _body(fixture)
        created = client.post(
            "/api/v1/finance/treasury/batches",
            headers=_headers(**{"Idempotency-Key": key}),
            json=body,
        )
        assert created.status_code == 201, created.text
        cast(FastAPI, client.app).state.test_batch_id = created.json()["batch"]["id"]
        assert created.headers["etag"] == '"1"'
        assert created.headers["idempotency-replayed"] == "false"
        assert created.json()["batch"]["status"] == "DRAFT"
        assert created.json()["batch"]["items"][0]["beneficiary_account_masked"] == "***7654"

        replay = client.post(
            "/api/v1/finance/treasury/batches",
            headers=_headers(**{"Idempotency-Key": key}),
            json=body,
        )
        assert replay.status_code == 201
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.json()["batch"]["id"] == created.json()["batch"]["id"]

        batch_id = created.json()["batch"]["id"]
        listing = client.get(
            "/api/v1/finance/treasury/batches",
            headers=_headers(),
            params={
                "company_id": str(data.company_id),
                "status": "DRAFT",
                "scheduled_from": "2026-12-01",
                "scheduled_to": "2026-12-31",
                "page_size": 1,
            },
        )
        assert listing.status_code == 200
        assert [value["id"] for value in listing.json()["data"]] == [batch_id]
        detail = client.get(
            f"/api/v1/finance/treasury/batches/{batch_id}?company_id={data.company_id}",
            headers=_headers(),
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"1"'
        assert [entry["to_status"] for entry in detail.json()["audit_history"]] == ["DRAFT"]

        dry_run_key = str(uuid4())
        dry_run = client.post(
            f"/api/v1/finance/treasury/batches/{batch_id}/dry-run?company_id={data.company_id}",
            headers=_headers(**{"If-Match": '"1"', "Idempotency-Key": dry_run_key}),
        )
        assert dry_run.status_code == 200, dry_run.text
        assert dry_run.json()["remittance"]["dry_run"] is True
        assert dry_run.json()["remittance"]["record_count"] == 3
        assert dry_run.headers["etag"] == '"1"'
        dry_run_replay = client.post(
            f"/api/v1/finance/treasury/batches/{batch_id}/dry-run?company_id={data.company_id}",
            headers=_headers(**{"If-Match": '"1"', "Idempotency-Key": dry_run_key}),
        )
        assert dry_run_replay.status_code == 200
        assert dry_run_replay.headers["idempotency-replayed"] == "true"


def test_remittance_m22_and_bank_return_confirmation() -> None:
    with treasury_api() as (client, fixture, resolver):
        data = fixture.matching.data
        created = _create(client, fixture)
        assert created.status_code == 201, created.text
        batch_id = UUID(created.json()["batch"]["id"])

        pending = client.post(
            f"/api/v1/finance/treasury/batches/{batch_id}/remittance?company_id={data.company_id}",
            headers=_headers(**{"If-Match": '"1"', "Idempotency-Key": str(uuid4())}),
            json={},
        )
        assert pending.status_code == 202, pending.text
        assert pending.json()["batch"]["status"] == "PENDING_APPROVAL"
        assert pending.headers["etag"] == '"2"'
        workflow_id = UUID(pending.json()["workflow_instance_id"])

        async def approve_workflow() -> None:
            async with data.database.session() as session, session.begin():
                workflows = WorkflowRepository(session, company_id=data.company_id)
                instance = await workflows.get_instance(workflow_id)
                assert instance is not None
                steps = await workflows.list_step_instances(workflow_instance_id=workflow_id)
                await apply_workflow_decision(
                    session,
                    DecideWorkflowInstance(
                        company_id=data.company_id,
                        workflow_instance_id=workflow_id,
                        step_instance_id=steps[0].id,
                        expected_version=instance.version,
                        decision=ApprovalDecisionKind.APPROVED,
                        reason_code="PAYMENT_BATCH_APPROVED",
                        comment="Approved for API integration test.",
                        metadata=CommandMetadata(uuid4(), uuid4()),
                    ),
                    actor_id=fixture.batch_approver,
                    actor_permissions=frozenset({str(FINANCE_TREASURY_BATCH_APPROVE)}),
                )

        assert client.portal is not None
        client.portal.call(approve_workflow)
        resolver.context = _context(fixture.batch_executor, data.company_id)
        submitted = client.post(
            f"/api/v1/finance/treasury/batches/{batch_id}/remittance?company_id={data.company_id}",
            headers=_headers(**{"If-Match": '"2"', "Idempotency-Key": str(uuid4())}),
            json={"workflow_instance_id": str(workflow_id)},
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["batch"]["status"] == "SUBMITTED"
        assert submitted.headers["etag"] == '"5"'
        assert submitted.json()["remittance"]["dry_run"] is False

        return_key = str(uuid4())
        bank_return = _cnab_240_return(batch_id, Decimal("125.40"))
        settled = client.post(
            "/api/v1/finance/treasury/returns",
            params={
                "company_id": str(data.company_id),
                "remittance_format": "CNAB_240",
            },
            headers=_headers(
                **{
                    "Content-Type": "text/plain",
                    "Idempotency-Key": return_key,
                }
            ),
            content=bank_return,
        )
        assert settled.status_code == 200, settled.text
        assert settled.json()["settlements"] == [
            {
                "payment_batch_id": str(batch_id),
                "status": "CONFIRMED",
                "version": 6,
                "replayed": False,
            }
        ]
        replay = client.post(
            "/api/v1/finance/treasury/returns",
            params={
                "company_id": str(data.company_id),
                "remittance_format": "CNAB_240",
            },
            headers=_headers(**{"Idempotency-Key": return_key}),
            content=bank_return,
        )
        assert replay.status_code == 200
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.json()["settlements"][0]["status"] == "CONFIRMED"


def test_etag_rbac_tenant_and_input_guards_fail_closed() -> None:
    with treasury_api() as (client, fixture, resolver):
        data = fixture.matching.data
        created = _create(client, fixture)
        assert created.status_code == 201
        batch_id = created.json()["batch"]["id"]
        url = f"/api/v1/finance/treasury/batches/{batch_id}/dry-run?company_id={data.company_id}"
        missing = client.post(url, headers=_headers(**{"Idempotency-Key": str(uuid4())}))
        assert missing.status_code == 428
        assert missing.json()["error"]["code"] == "PRECONDITION_REQUIRED"
        stale = client.post(
            url,
            headers=_headers(**{"If-Match": '"99"', "Idempotency-Key": str(uuid4())}),
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
        invalid_period = client.get(
            "/api/v1/finance/treasury/batches",
            headers=_headers(),
            params={
                "company_id": str(data.company_id),
                "scheduled_from": "2026-12-31",
                "scheduled_to": "2026-12-01",
            },
        )
        assert invalid_period.status_code == 422
        assert invalid_period.json()["error"]["code"] == "VALIDATION_ERROR"

        foreign = client.get(
            f"/api/v1/finance/treasury/batches/{batch_id}?company_id={data.other_company_id}",
            headers=_headers(),
        )
        assert foreign.status_code == 404
        assert foreign.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

        assert resolver.context is not None
        resolver.context = replace(
            resolver.context,
            permissions=frozenset({FINANCE_TREASURY_READ}),
        )
        denied = _create(client, fixture)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PERMISSION_FORBIDDEN"

        application = cast(FastAPI, client.app)
        commands = application.state.finance_treasury
        application.state.finance_treasury = None
        try:
            unavailable = client.post(
                url,
                headers=_headers(**{"If-Match": '"1"', "Idempotency-Key": str(uuid4())}),
            )
            assert unavailable.status_code == 503
            assert unavailable.json()["error"]["code"] == "FINANCE_TREASURY_UNAVAILABLE"
        finally:
            application.state.finance_treasury = commands


def _cnab_240_return(batch_id: UUID, amount: Decimal) -> bytes:
    header = ("0" + "API-RETURN-176".ljust(40)).ljust(240)
    cents = str(int(amount * 100)).zfill(18)
    detail = (
        "3"
        + batch_id.hex
        + "BANK-PROTOCOL-176".ljust(40)
        + "00"
        + cents
        + (datetime.now(UTC) + timedelta(days=1)).strftime("%Y%m%d")
        + "".ljust(80)
    ).ljust(240)
    trailer = "9".ljust(240)
    return f"{header}\n{detail}\n{trailer}\n".encode("ascii")


__all__: list[str] = []
