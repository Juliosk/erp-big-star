"""M22 Workflow APIs use real PostgreSQL with only identity resolution stubbed."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

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
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)
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


def _definition_payload(company_id: str, *, code: str = "WF-API") -> dict[str, object]:
    return {
        "company_id": company_id,
        "code": code,
        "name": "Aprovação de descontos",
        "source_module": "SALES",
        "source_type": "QUOTE",
        "approval_mode": "SEQUENTIAL",
        "steps": [
            {
                "sequence": 1,
                "code": "MANAGER",
                "name": "Gerência comercial",
                "required_permission": "workflow.approval.decide",
                "threshold_amount": "100.00",
            }
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
