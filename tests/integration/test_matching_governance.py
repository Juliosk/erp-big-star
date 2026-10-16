"""M6/M22 governed matching overrides against real PostgreSQL."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Scope,
    ScopeType,
)
from erp.modules.procurement.application import (
    PROCUREMENT_MATCHING_EXECUTE,
    PROCUREMENT_MATCHING_READ,
)
from erp.modules.procurement.domain import ThreeWayMatchSession
from erp.modules.procurement.infrastructure import ThreeWayMatchRepository
from erp.modules.workflow.application import (
    WORKFLOW_APPROVAL_DECIDE,
    WORKFLOW_REQUEST_CREATE,
)
from erp.modules.workflow.domain import (
    ApprovalMode,
    WorkflowDefinition,
    WorkflowStepDefinition,
)
from erp.modules.workflow.infrastructure import (
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowRepository,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)
from erp.platform.audit import AuditEventModel
from erp.platform.idempotency import IdempotencyRecordModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_matching_repository import MatchingFixture, matching_fixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "matching-governance-token" else None


@dataclass
class GovernanceFixture:
    client: TestClient
    matching: MatchingFixture
    resolver: ResolverStub
    discrepancy: ThreeWayMatchSession

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer matching-governance-token"}


@asynccontextmanager
async def _governance_data() -> AsyncIterator[tuple[MatchingFixture, ThreeWayMatchSession]]:
    async with matching_fixture() as fixture:
        pending = replace(
            fixture.aggregate,
            lines=(
                replace(
                    fixture.aggregate.lines[0],
                    invoiced_unit_price=fixture.aggregate.lines[0].invoiced_unit_price
                    + Decimal("10.00"),
                ),
            ),
        )
        async with fixture.data.database.session() as session, session.begin():
            repository = ThreeWayMatchRepository(session, company_id=fixture.data.company_id)
            await repository.add(pending, actor_id=fixture.data.actor_id)
            running = pending.start(occurred_at=pending.created_at)
            await repository.save(running, actor_id=fixture.data.actor_id)
            discrepancy = running.evaluate(occurred_at=running.started_at)
            await repository.save(discrepancy, actor_id=fixture.data.actor_id)
            workflow_repository = WorkflowRepository(session, company_id=fixture.data.company_id)
            definition = WorkflowDefinition.create(
                company_id=fixture.data.company_id,
                code="MATCHING-OVERRIDE",
                name="Alçadas de exceção do three-way match",
                source_module="PROCUREMENT",
                source_type="MATCHING_OVERRIDE",
                approval_mode=ApprovalMode.SEQUENTIAL,
            )
            steps = (
                WorkflowStepDefinition.create(
                    company_id=fixture.data.company_id,
                    sequence=1,
                    code="SUPERVISOR",
                    name="Supervisor de Compras",
                    required_permission=str(WORKFLOW_APPROVAL_DECIDE),
                    threshold_amount="0.01",
                ),
                WorkflowStepDefinition.create(
                    company_id=fixture.data.company_id,
                    sequence=2,
                    code="FINANCE",
                    name="Gestor Financeiro",
                    required_permission=str(WORKFLOW_APPROVAL_DECIDE),
                    threshold_amount=None,
                ),
            )
            await workflow_repository.add_definition(
                definition, steps=steps, actor_id=fixture.data.actor_id
            )
        try:
            yield fixture, discrepancy
        finally:
            await _cleanup_governance(fixture)


async def _cleanup_governance(fixture: MatchingFixture) -> None:
    company_id = fixture.data.company_id
    async with fixture.data.database.session() as session, session.begin():
        await session.execute(
            delete(OutboxEventModel).where(
                OutboxEventModel.source_module.in_(("procurement", "workflow")),
                OutboxEventModel.aggregate_id.in_(
                    select(WorkflowInstanceModel.id).where(
                        WorkflowInstanceModel.company_id == company_id
                    )
                )
                | (OutboxEventModel.aggregate_id == fixture.aggregate.id),
            )
        )
        await session.execute(
            delete(AuditEventModel).where(
                AuditEventModel.company_id == company_id,
                AuditEventModel.module.in_(("procurement", "workflow")),
            )
        )
        await session.execute(
            delete(IdempotencyRecordModel).where(
                IdempotencyRecordModel.scope.like(f"procurement-matching-governance:{company_id}:%")
            )
        )
        await session.execute(
            delete(ApprovalDecisionModel).where(ApprovalDecisionModel.company_id == company_id)
        )
        await session.execute(
            delete(WorkflowStepInstanceModel).where(
                WorkflowStepInstanceModel.company_id == company_id
            )
        )
        await session.execute(
            delete(WorkflowInstanceModel).where(WorkflowInstanceModel.company_id == company_id)
        )
        await session.execute(
            delete(WorkflowStepDefinitionModel).where(
                WorkflowStepDefinitionModel.company_id == company_id
            )
        )
        await session.execute(
            delete(WorkflowDefinitionModel).where(WorkflowDefinitionModel.company_id == company_id)
        )


def _context(fixture: MatchingFixture, actor_id: UUID) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(
            actor_id,
            uuid4(),
            AuthenticationLevel.LEVEL_1,
        ),
        permissions=frozenset(
            {
                PROCUREMENT_MATCHING_EXECUTE,
                PROCUREMENT_MATCHING_READ,
                WORKFLOW_REQUEST_CREATE,
                WORKFLOW_APPROVAL_DECIDE,
            }
        ),
        scopes=frozenset({Scope(ScopeType.COMPANY, fixture.data.company_id)}),
    )


@contextmanager
def governance_api() -> Iterator[GovernanceFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = _governance_data()
        fixture, discrepancy = client.portal.call(manager.__aenter__)
        resolver.context = _context(fixture, fixture.data.actor_id)
        try:
            yield GovernanceFixture(client, fixture, resolver, discrepancy)
        finally:
            client.portal.call(manager.__aexit__, None, None, None)


def _request_override(api: GovernanceFixture, key: str = "override-request") -> Any:
    response = api.client.post(
        f"/api/v1/procurement/matching-sessions/{api.discrepancy.id}/override",
        params={"company_id": str(api.matching.data.company_id)},
        json={"justification": "Divergência comercial validada para análise formal."},
        headers={
            **api.headers,
            "If-Match": '"3"',
            "Idempotency-Key": key,
        },
    )
    assert response.status_code == 200, response.text
    return response


def _decide(
    api: GovernanceFixture,
    request_payload: dict[str, Any],
    *,
    step_id: str,
    workflow_version: int,
    decision: str,
    key: str,
) -> Any:
    return api.client.post(
        f"/api/v1/procurement/matching-sessions/{api.discrepancy.id}/override/decide",
        params={"company_id": str(api.matching.data.company_id)},
        json={
            "workflow_instance_id": request_payload["workflow"]["id"],
            "workflow_step_instance_id": step_id,
            "workflow_expected_version": workflow_version,
            "decision": decision,
            "reason": "Decisão formal documentada com evidências suficientes.",
        },
        headers={
            **api.headers,
            "If-Match": '"3"',
            "Idempotency-Key": key,
        },
    )


def test_override_uses_m22_levels_enforces_sod_and_commits_audit_outbox_atomically() -> None:
    with governance_api() as api:
        requested = _request_override(api)
        payload = requested.json()
        assert requested.headers["etag"] == '"3"'
        assert payload["workflow"]["status"] == "PENDING"
        assert payload["workflow"]["discrepancy_amount"] == "100.00"
        assert [step["status"] for step in payload["workflow"]["steps"]] == [
            "ACTIVE",
            "WAITING",
        ]

        blocked = _decide(
            api,
            payload,
            step_id=payload["workflow"]["steps"][0]["id"],
            workflow_version=1,
            decision="APPROVE",
            key="override-sod-block",
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "SOD_VIOLATION"

        api.resolver.context = _context(api.matching, uuid4())
        level_one = _decide(
            api,
            payload,
            step_id=payload["workflow"]["steps"][0]["id"],
            workflow_version=1,
            decision="APPROVE",
            key="override-level-one",
        )
        assert level_one.status_code == 200, level_one.text
        level_one_payload = level_one.json()
        assert level_one_payload["session"]["status"] == "DISCREPANCY_DETECTED"
        assert level_one_payload["workflow"]["status"] == "PENDING"
        assert level_one_payload["workflow"]["version"] == 2
        active = next(
            step for step in level_one_payload["workflow"]["steps"] if step["status"] == "ACTIVE"
        )

        final = _decide(
            api,
            level_one_payload,
            step_id=active["id"],
            workflow_version=2,
            decision="APPROVE",
            key="override-level-two",
        )
        assert final.status_code == 200, final.text
        assert final.headers["etag"] == '"4"'
        assert final.json()["session"]["status"] == "OVERRIDDEN"
        assert final.json()["workflow"]["status"] == "APPROVED"

        replay = _decide(
            api,
            level_one_payload,
            step_id=active["id"],
            workflow_version=2,
            decision="APPROVE",
            key="override-level-two",
        )
        assert replay.status_code == 200
        assert replay.json() == final.json()

        assert api.client.portal is not None

        async def evidence() -> tuple[list[str], list[str], int]:
            async with api.matching.data.database.session() as session:
                event_types = list(
                    await session.scalars(
                        select(OutboxEventModel.event_type).where(
                            OutboxEventModel.aggregate_id.in_(
                                (
                                    api.discrepancy.id,
                                    UUID(payload["workflow"]["id"]),
                                )
                            )
                        )
                    )
                )
                audit_operations = list(
                    await session.scalars(
                        select(AuditEventModel.operation).where(
                            AuditEventModel.company_id == api.matching.data.company_id,
                            AuditEventModel.entity_id == api.discrepancy.id,
                        )
                    )
                )
                decisions = await session.scalar(
                    select(func.count())
                    .select_from(ApprovalDecisionModel)
                    .where(
                        ApprovalDecisionModel.workflow_instance_id
                        == UUID(payload["workflow"]["id"])
                    )
                )
                return event_types, audit_operations, int(decisions or 0)

        event_types, audit_operations, decision_count = api.client.portal.call(evidence)
        assert "MatchingOverrideRequested" in event_types
        assert "MatchingOverrideApproved" in event_types
        assert audit_operations == [
            "MatchingOverrideRequested",
            "MatchingOverrideApproved",
        ]
        assert decision_count == 2


def test_override_rejection_is_final_and_cross_tenant_access_is_hidden() -> None:
    with governance_api() as api:
        requested = _request_override(api, "override-reject-request")
        payload = requested.json()
        api.resolver.context = _context(api.matching, uuid4())
        rejected = _decide(
            api,
            payload,
            step_id=payload["workflow"]["steps"][0]["id"],
            workflow_version=1,
            decision="REJECT",
            key="override-reject",
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["session"]["status"] == "REJECTED"
        assert rejected.json()["workflow"]["status"] == "REJECTED"
        assert api.client.portal is not None

        async def rejected_event_exists() -> bool:
            async with api.matching.data.database.session() as session:
                count = await session.scalar(
                    select(func.count()).select_from(OutboxEventModel).where(
                        OutboxEventModel.aggregate_id == api.discrepancy.id,
                        OutboxEventModel.event_type == "MatchingOverrideRejected",
                    )
                )
                return bool(count)

        assert api.client.portal.call(rejected_event_exists)

        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            scopes=frozenset({Scope(ScopeType.COMPANY, api.matching.data.other_company_id)}),
        )
        hidden = api.client.post(
            f"/api/v1/procurement/matching-sessions/{api.discrepancy.id}/override",
            params={"company_id": str(api.matching.data.other_company_id)},
            json={"justification": "Tentativa fora do escopo da empresa de trabalho."},
            headers={
                **api.headers,
                "If-Match": '"3"',
                "Idempotency-Key": "override-cross-tenant",
            },
        )
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
