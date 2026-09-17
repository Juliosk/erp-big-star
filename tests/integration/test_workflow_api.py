"""M22 Workflow APIs use real PostgreSQL with only identity resolution stubbed."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.workflow.application.permissions import (
    WORKFLOW_APPROVAL_DECIDE,
    WORKFLOW_DEFINITION_MANAGE,
    WORKFLOW_REQUEST_CREATE,
    WORKFLOW_REQUEST_READ,
)
from erp.modules.workflow.infrastructure import (
    WORKFLOW_INSTANCE_APPROVED,
    WORKFLOW_INSTANCE_REJECTED,
    WORKFLOW_STEP_APPROVED,
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)
from erp.platform.audit import AuditEventModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_product_persistence import Fixture, fixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "workflow-test-token" else None


@dataclass
class WorkflowApiFixture:
    client: TestClient
    data: Fixture
    resolver: ResolverStub

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer workflow-test-token"}


async def _cleanup_workflow(data: Fixture) -> None:
    company_ids = (data.company_id, data.other_company_id)
    async with data.database.session() as session, session.begin():
        await session.execute(
            delete(OutboxEventModel).where(OutboxEventModel.source_module == "workflow")
        )
        await session.execute(
            delete(AuditEventModel).where(
                AuditEventModel.module == "workflow",
                AuditEventModel.company_id.in_(company_ids),
            )
        )
        await session.execute(
            delete(ApprovalDecisionModel).where(
                ApprovalDecisionModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(WorkflowStepInstanceModel).where(
                WorkflowStepInstanceModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(WorkflowInstanceModel).where(
                WorkflowInstanceModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(WorkflowStepDefinitionModel).where(
                WorkflowStepDefinitionModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(WorkflowDefinitionModel).where(
                WorkflowDefinitionModel.company_id.in_(company_ids)
            )
        )


@contextmanager
def workflow_api() -> Iterator[WorkflowApiFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = fixture()
        data = client.portal.call(manager.__aenter__)
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(
                data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1
            ),
            permissions=frozenset({WORKFLOW_DEFINITION_MANAGE}),
            scopes=frozenset(
                {
                    Scope(ScopeType.COMPANY, data.company_id),
                    Scope(ScopeType.COMPANY, data.other_company_id),
                }
            ),
        )
        try:
            yield WorkflowApiFixture(client, data, resolver)
        finally:
            try:
                client.portal.call(_cleanup_workflow, data)
            finally:
                client.portal.call(manager.__aexit__, None, None, None)


def _definition_payload(
    company_id: str,
    *,
    code: str = "WF-API",
    approval_mode: str = "SEQUENTIAL",
    steps_count: int = 1,
    required_permission: str = "workflow.approval.decide",
) -> dict[str, object]:
    return {
        "company_id": company_id,
        "code": code,
        "name": "Aprovação de descontos",
        "source_module": "SALES",
        "source_type": "QUOTE",
        "approval_mode": approval_mode,
        "steps": [
            {
                "sequence": sequence,
                "code": f"STEP-{sequence}",
                "name": f"Aprovação {sequence}",
                "required_permission": required_permission,
                "threshold_amount": "100.00",
            }
            for sequence in range(1, steps_count + 1)
        ],
    }


def _grant_all_workflow(api: WorkflowApiFixture) -> None:
    assert api.resolver.context is not None
    api.resolver.context = replace(
        api.resolver.context,
        permissions=frozenset(
            {
                WORKFLOW_DEFINITION_MANAGE,
                WORKFLOW_APPROVAL_DECIDE,
                WORKFLOW_REQUEST_CREATE,
                WORKFLOW_REQUEST_READ,
            }
        ),
    )


def test_workflow_definition_api_create_list_get_and_deactivate() -> None:
    with workflow_api() as api:
        created = api.client.post(
            "/api/v1/workflow/definitions",
            json=_definition_payload(str(api.data.company_id)),
            headers=api.headers,
        )
        assert created.status_code == 201
        assert created.headers["etag"] == '"1"'
        body = created.json()
        definition = body["definition"]
        assert definition["company_id"] == str(api.data.company_id)
        assert definition["code"] == "WF-API"
        assert definition["active"] is True
        assert body["steps"][0]["threshold_amount"] == "100.00"

        listed = api.client.get(
            f"/api/v1/workflow/definitions?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["data"]] == [definition["id"]]

        detail = api.client.get(
            f"/api/v1/workflow/definitions/{definition['id']}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"1"'
        assert detail.json()["definition"] == definition

        deactivated = api.client.post(
            (
                f"/api/v1/workflow/definitions/{definition['id']}/deactivate"
                f"?company_id={api.data.company_id}"
            ),
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert deactivated.status_code == 200
        assert deactivated.headers["etag"] == '"2"'
        assert deactivated.json()["definition"]["active"] is False


def test_workflow_definition_api_enforces_rbac_scope_if_match_and_conflicts() -> None:
    with workflow_api() as api:
        created = api.client.post(
            "/api/v1/workflow/definitions",
            json=_definition_payload(str(api.data.company_id), code="WF-GUARD"),
            headers=api.headers,
        )
        assert created.status_code == 201
        definition_id = created.json()["definition"]["id"]

        original = api.resolver.context
        assert original is not None
        api.resolver.context = replace(original, permissions=frozenset())
        denied = api.client.get(
            f"/api/v1/workflow/definitions?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PERMISSION_FORBIDDEN"
        api.resolver.context = replace(
            original,
            scopes=frozenset({Scope(ScopeType.COMPANY, api.data.other_company_id)}),
        )
        scoped = api.client.get(
            f"/api/v1/workflow/definitions?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert scoped.status_code == 404
        assert scoped.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
        api.resolver.context = original

        duplicate = api.client.post(
            "/api/v1/workflow/definitions",
            json=_definition_payload(str(api.data.company_id), code="WF-GUARD"),
            headers=api.headers,
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "WORKFLOW_DEFINITION_CONFLICT"

        missing_if_match = api.client.post(
            (
                f"/api/v1/workflow/definitions/{definition_id}/deactivate"
                f"?company_id={api.data.company_id}"
            ),
            headers=api.headers,
        )
        assert missing_if_match.status_code == 428
        assert missing_if_match.json()["error"]["code"] == "PRECONDITION_REQUIRED"

        conflict = api.client.post(
            (
                f"/api/v1/workflow/definitions/{definition_id}/deactivate"
                f"?company_id={api.data.company_id}"
            ),
            headers={**api.headers, "If-Match": '"7"'},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "VERSION_CONFLICT"


def test_workflow_instance_api_opens_request_from_active_definition() -> None:
    with workflow_api() as api:
        _grant_all_workflow(api)
        definition = api.client.post(
            "/api/v1/workflow/definitions",
            json=_definition_payload(str(api.data.company_id), code="WF-INSTANCE"),
            headers=api.headers,
        ).json()["definition"]
        source_id = uuid4()

        opened = api.client.post(
            "/api/v1/workflow/instances",
            json={
                "company_id": str(api.data.company_id),
                "source_module": "sales",
                "source_type": "quote",
                "source_id": str(source_id),
                "source_fingerprint": "quote:instance:v1",
            },
            headers=api.headers,
        )
        assert opened.status_code == 201
        assert opened.headers["etag"] == '"1"'
        body = opened.json()
        instance = body["instance"]
        assert instance["company_id"] == str(api.data.company_id)
        assert instance["definition_id"] == definition["id"]
        assert instance["source_module"] == "SALES"
        assert instance["source_type"] == "QUOTE"
        assert instance["status"] == "PENDING"
        assert body["steps"][0]["status"] == "ACTIVE"

        detail = api.client.get(
            f"/api/v1/workflow/instances/{instance['id']}?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"1"'
        assert detail.json() == body

        duplicate = api.client.post(
            "/api/v1/workflow/instances",
            json={
                "company_id": str(api.data.company_id),
                "source_module": "SALES",
                "source_type": "QUOTE",
                "source_id": str(source_id),
                "source_fingerprint": "quote:instance:v1",
            },
            headers=api.headers,
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "WORKFLOW_INSTANCE_CONFLICT"


def test_workflow_instance_api_requires_create_permission_and_active_definition() -> None:
    with workflow_api() as api:
        source_id = uuid4()
        denied = api.client.post(
            "/api/v1/workflow/instances",
            json={
                "company_id": str(api.data.company_id),
                "source_module": "SALES",
                "source_type": "QUOTE",
                "source_id": str(source_id),
                "source_fingerprint": "quote:no-permission",
            },
            headers=api.headers,
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PERMISSION_FORBIDDEN"

        _grant_all_workflow(api)
        missing_definition = api.client.post(
            "/api/v1/workflow/instances",
            json={
                "company_id": str(api.data.company_id),
                "source_module": "SALES",
                "source_type": "ORDER",
                "source_id": str(source_id),
                "source_fingerprint": "order:no-definition",
            },
            headers=api.headers,
        )
        assert missing_definition.status_code == 404
        assert missing_definition.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_pending_approvals_api_filters_by_actor_permissions_and_source_type() -> None:
    with workflow_api() as api:
        _grant_all_workflow(api)
        api.client.post(
            "/api/v1/workflow/definitions",
            json=_definition_payload(str(api.data.company_id), code="WF-PENDING"),
            headers=api.headers,
        )
        opened = api.client.post(
            "/api/v1/workflow/instances",
            json={
                "company_id": str(api.data.company_id),
                "source_module": "SALES",
                "source_type": "QUOTE",
                "source_id": str(uuid4()),
                "source_fingerprint": "quote:pending:v1",
            },
            headers=api.headers,
        )
        assert opened.status_code == 201
        instance_id = opened.json()["instance"]["id"]

        pending = api.client.get(
            (
                f"/api/v1/workflow/approvals/pending?company_id={api.data.company_id}"
                "&source_module=sales&source_type=quote"
            ),
            headers=api.headers,
        )
        assert pending.status_code == 200
        assert pending.json()["meta"] == {"page": 1, "page_size": 50, "has_more": False}
        assert [item["instance"]["id"] for item in pending.json()["data"]] == [instance_id]
        assert pending.json()["data"][0]["step"]["required_permission"] == (
            "workflow.approval.decide"
        )

        filtered_out = api.client.get(
            (
                f"/api/v1/workflow/approvals/pending?company_id={api.data.company_id}"
                "&source_module=sales&source_type=order"
            ),
            headers=api.headers,
        )
        assert filtered_out.status_code == 200
        assert filtered_out.json()["data"] == []

        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            permissions=frozenset({WORKFLOW_REQUEST_READ}),
        )
        no_step_permission = api.client.get(
            f"/api/v1/workflow/approvals/pending?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert no_step_permission.status_code == 200
        assert no_step_permission.json()["data"] == []


def test_pending_approvals_api_requires_read_permission() -> None:
    with workflow_api() as api:
        denied = api.client.get(
            f"/api/v1/workflow/approvals/pending?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PERMISSION_FORBIDDEN"


def test_workflow_decision_api_advances_sequential_steps_and_versions() -> None:
    with workflow_api() as api:
        _grant_all_workflow(api)
        api.client.post(
            "/api/v1/workflow/definitions",
            json=_definition_payload(
                str(api.data.company_id), code="WF-DECIDE-SEQ", steps_count=2
            ),
            headers=api.headers,
        )
        opened = api.client.post(
            "/api/v1/workflow/instances",
            json={
                "company_id": str(api.data.company_id),
                "source_module": "SALES",
                "source_type": "QUOTE",
                "source_id": str(uuid4()),
                "source_fingerprint": "quote:decision:sequential",
            },
            headers=api.headers,
        ).json()
        first_step, second_step = opened["steps"]

        first_decision = api.client.post(
            f"/api/v1/workflow/instances/{opened['instance']['id']}/decide",
            json={
                "company_id": str(api.data.company_id),
                "step_instance_id": first_step["id"],
                "decision": "APPROVED",
                "reason_code": "OK",
                "comment": "primeiro nível",
            },
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert first_decision.status_code == 200
        assert first_decision.headers["etag"] == '"2"'
        first_body = first_decision.json()
        assert first_body["event_id"] is not None
        assert first_body["audit_event_id"] is not None
        assert first_body["detail"]["instance"]["status"] == "PENDING"
        assert first_body["detail"]["instance"]["current_step_sequence"] == 2
        assert [step["status"] for step in first_body["detail"]["steps"]] == [
            "APPROVED",
            "ACTIVE",
        ]

        stale = api.client.post(
            f"/api/v1/workflow/instances/{opened['instance']['id']}/decide",
            json={
                "company_id": str(api.data.company_id),
                "step_instance_id": second_step["id"],
                "decision": "APPROVED",
            },
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"

        second_decision = api.client.post(
            f"/api/v1/workflow/instances/{opened['instance']['id']}/decide",
            json={
                "company_id": str(api.data.company_id),
                "step_instance_id": second_step["id"],
                "decision": "APPROVED",
            },
            headers={**api.headers, "If-Match": '"2"'},
        )
        assert second_decision.status_code == 200
        assert second_decision.headers["etag"] == '"3"'
        assert second_decision.json()["detail"]["instance"]["status"] == "APPROVED"
        assert second_decision.json()["event_id"] is not None

        async def count_effects() -> tuple[int, int, int]:
            async with api.data.database.session() as session:
                step_events = await session.scalar(
                    select(func.count()).select_from(OutboxEventModel).where(
                        OutboxEventModel.source_module == "workflow",
                        OutboxEventModel.event_type == WORKFLOW_STEP_APPROVED,
                        OutboxEventModel.aggregate_id == UUID(opened["instance"]["id"]),
                    )
                )
                approved_events = await session.scalar(
                    select(func.count()).select_from(OutboxEventModel).where(
                        OutboxEventModel.source_module == "workflow",
                        OutboxEventModel.event_type == WORKFLOW_INSTANCE_APPROVED,
                        OutboxEventModel.aggregate_id == UUID(opened["instance"]["id"]),
                    )
                )
                audits = await session.scalar(
                    select(func.count()).select_from(AuditEventModel).where(
                        AuditEventModel.module == "workflow",
                        AuditEventModel.entity_id == UUID(opened["instance"]["id"]),
                    )
                )
                return int(step_events or 0), int(approved_events or 0), int(audits or 0)

        assert api.client.portal is not None
        assert api.client.portal.call(count_effects) == (1, 1, 2)


def test_workflow_decision_api_rejects_highest_level_and_finishes_cumulative() -> None:
    with workflow_api() as api:
        _grant_all_workflow(api)
        api.client.post(
            "/api/v1/workflow/definitions",
            json=_definition_payload(
                str(api.data.company_id),
                code="WF-DECIDE-HIGH",
                approval_mode="HIGHEST_LEVEL",
                steps_count=2,
            ),
            headers=api.headers,
        )
        highest = api.client.post(
            "/api/v1/workflow/instances",
            json={
                "company_id": str(api.data.company_id),
                "source_module": "SALES",
                "source_type": "QUOTE",
                "source_id": str(uuid4()),
                "source_fingerprint": "quote:decision:highest",
            },
            headers=api.headers,
        ).json()
        assert [step["status"] for step in highest["steps"]] == ["WAITING", "ACTIVE"]
        rejected = api.client.post(
            f"/api/v1/workflow/instances/{highest['instance']['id']}/decide",
            json={
                "company_id": str(api.data.company_id),
                "step_instance_id": highest["steps"][1]["id"],
                "decision": "REJECTED",
                "reason_code": "DENIED",
            },
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert rejected.status_code == 200
        assert rejected.json()["detail"]["instance"]["status"] == "REJECTED"
        assert rejected.json()["event_id"] is not None
        assert rejected.json()["audit_event_id"] is not None

        async def count_rejection() -> int:
            async with api.data.database.session() as session:
                value = await session.scalar(
                    select(func.count()).select_from(OutboxEventModel).where(
                        OutboxEventModel.source_module == "workflow",
                        OutboxEventModel.event_type == WORKFLOW_INSTANCE_REJECTED,
                        OutboxEventModel.aggregate_id == UUID(highest["instance"]["id"]),
                    )
                )
                return int(value or 0)

        assert api.client.portal is not None
        assert api.client.portal.call(count_rejection) == 1

    with workflow_api() as api:
        _grant_all_workflow(api)
        api.client.post(
            "/api/v1/workflow/definitions",
            json=_definition_payload(
                str(api.data.company_id),
                code="WF-DECIDE-CUM",
                approval_mode="CUMULATIVE",
                steps_count=2,
            ),
            headers=api.headers,
        )
        cumulative = api.client.post(
            "/api/v1/workflow/instances",
            json={
                "company_id": str(api.data.company_id),
                "source_module": "SALES",
                "source_type": "QUOTE",
                "source_id": str(uuid4()),
                "source_fingerprint": "quote:decision:cumulative",
            },
            headers=api.headers,
        ).json()
        assert [step["status"] for step in cumulative["steps"]] == ["ACTIVE", "ACTIVE"]
        first = api.client.post(
            f"/api/v1/workflow/instances/{cumulative['instance']['id']}/decide",
            json={
                "company_id": str(api.data.company_id),
                "step_instance_id": cumulative["steps"][0]["id"],
                "decision": "APPROVED",
            },
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert first.status_code == 200
        assert first.json()["detail"]["instance"]["status"] == "PENDING"
        final = api.client.post(
            f"/api/v1/workflow/instances/{cumulative['instance']['id']}/decide",
            json={
                "company_id": str(api.data.company_id),
                "step_instance_id": cumulative["steps"][1]["id"],
                "decision": "APPROVED",
            },
            headers={**api.headers, "If-Match": '"2"'},
        )
        assert final.status_code == 200
        assert final.json()["detail"]["instance"]["status"] == "APPROVED"


def test_workflow_decision_api_requires_if_match_and_step_permission() -> None:
    with workflow_api() as api:
        _grant_all_workflow(api)
        api.client.post(
            "/api/v1/workflow/definitions",
            json=_definition_payload(
                str(api.data.company_id),
                code="WF-DECIDE-GUARD",
                required_permission="sales.quote.approve",
            ),
            headers=api.headers,
        )
        opened = api.client.post(
            "/api/v1/workflow/instances",
            json={
                "company_id": str(api.data.company_id),
                "source_module": "SALES",
                "source_type": "QUOTE",
                "source_id": str(uuid4()),
                "source_fingerprint": "quote:decision:guard",
            },
            headers=api.headers,
        ).json()
        missing_if_match = api.client.post(
            f"/api/v1/workflow/instances/{opened['instance']['id']}/decide",
            json={
                "company_id": str(api.data.company_id),
                "step_instance_id": opened["steps"][0]["id"],
                "decision": "APPROVED",
            },
            headers=api.headers,
        )
        assert missing_if_match.status_code == 428
        assert missing_if_match.json()["error"]["code"] == "PRECONDITION_REQUIRED"

        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            permissions=frozenset({WORKFLOW_APPROVAL_DECIDE}),
        )
        step_permission_denied = api.client.post(
            f"/api/v1/workflow/instances/{opened['instance']['id']}/decide",
            json={
                "company_id": str(api.data.company_id),
                "step_instance_id": opened["steps"][0]["id"],
                "decision": "APPROVED",
            },
            headers={**api.headers, "If-Match": '"1"'},
        )
        assert step_permission_denied.status_code == 403
        assert step_permission_denied.json()["error"]["code"] == "PERMISSION_FORBIDDEN"
