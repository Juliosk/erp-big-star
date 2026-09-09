"""M14 duplicate detection and merge requests preserve auditability."""

from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from erp.modules.admin.domain import Scope, ScopeType
from erp.modules.customer.application.permissions import (
    CUSTOMER_CREATE,
    CUSTOMER_MERGE,
    CUSTOMER_READ,
)
from erp.modules.customer.infrastructure import (
    CustomerDuplicateCandidateModel,
    CustomerMergeRequestModel,
)
from erp.platform.audit import AuditEventModel, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxEventModel, OutboxService
from tests.integration.customer_api_support import CustomerApiFixture, customer_api
from tests.integration.test_customer_creation_api import creation_body

pytestmark = pytest.mark.integration


def allow_duplicate_flow(api: CustomerApiFixture) -> None:
    assert api.resolver.context is not None
    api.resolver.context = replace(
        api.resolver.context,
        permissions=frozenset({CUSTOMER_CREATE, CUSTOMER_READ, CUSTOMER_MERGE}),
    )


def create_customer(
    api: CustomerApiFixture,
    *,
    cpf: str,
    legal_name: str,
    trade_name: str | None = None,
) -> dict[str, Any]:
    body = {
        **creation_body(api, cpf=cpf),
        "legal_name": legal_name,
        "trade_name": trade_name,
    }
    response = api.client.post(
        "/api/v1/customers",
        json=body,
        headers={**api.headers, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json()["customer"])


def duplicate_counts(api: CustomerApiFixture) -> tuple[int, int, int, int]:
    async def query() -> tuple[int, int, int, int]:
        async with api.data.database.session() as session:
            candidates = await session.scalar(
                select(func.count())
                .select_from(CustomerDuplicateCandidateModel)
                .where(CustomerDuplicateCandidateModel.company_id == api.data.company_id)
            )
            merge_requests = await session.scalar(
                select(func.count())
                .select_from(CustomerMergeRequestModel)
                .where(CustomerMergeRequestModel.company_id == api.data.company_id)
            )
            audit = await session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(
                    AuditEventModel.company_id == api.data.company_id,
                    AuditEventModel.module == "crm",
                    AuditEventModel.operation == "MergeApprovalRequested",
                )
            )
            outbox = await session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(
                    OutboxEventModel.event_type == "MergeApprovalRequested",
                )
            )
            return candidates or 0, merge_requests or 0, audit or 0, outbox or 0

    assert api.client.portal is not None
    return cast(tuple[int, int, int, int], api.client.portal.call(query))


def test_detect_duplicates_and_request_merge_are_traceable() -> None:
    with customer_api() as api:
        allow_duplicate_flow(api)
        source = create_customer(
            api, cpf="52998224725", legal_name="Maria Souza", trade_name="Maria"
        )
        candidate = create_customer(
            api, cpf="15350946056", legal_name="Maria Sousa", trade_name="Maria S."
        )
        detection = api.client.post(
            f"/api/v1/customers/{source['id']}/duplicates/detect?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert detection.status_code == 200
        body = detection.json()
        assert body["data"][0]["candidate_customer_id"] == candidate["id"]
        assert body["data"][0]["confidence"] >= 86
        assert "LEGAL_NAME_SIMILAR" in body["data"][0]["reason_codes"]

        correlation_id, request_id = uuid4(), uuid4()
        merge = api.client.post(
            f"/api/v1/customers/{source['id']}/merge-requests",
            json={
                "company_id": str(api.data.company_id),
                "candidate_customer_id": candidate["id"],
                "surviving_customer_id": source["id"],
                "reason": "Possivel cliente duplicado validado pelo fiscal.",
            },
            headers={
                **api.headers,
                "X-Correlation-ID": str(correlation_id),
                "X-Request-ID": str(request_id),
            },
        )
        assert merge.status_code == 201
        assert merge.headers["etag"] == '"1"'
        merge_body = merge.json()
        assert merge_body["status"] == "PENDING_APPROVAL"
        assert merge_body["source_customer_id"] == source["id"]
        assert merge_body["candidate_customer_id"] == candidate["id"]
        assert merge_body["surviving_customer_id"] == source["id"]
        assert duplicate_counts(api) == (1, 1, 1, 1)

        async def verify() -> None:
            async with api.data.database.session() as session:
                candidate_row = await session.scalar(
                    select(CustomerDuplicateCandidateModel).where(
                        CustomerDuplicateCandidateModel.source_customer_id == UUID(source["id"])
                    )
                )
                outbox = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == UUID(merge_body["event_id"])
                    )
                )
                audit = await session.get(AuditEventModel, UUID(merge_body["audit_event_id"]))
                assert candidate_row is not None
                assert candidate_row.status == "MERGE_REQUESTED"
                assert outbox is not None
                assert audit is not None
                envelope = MessageEnvelope.model_validate(outbox.payload)
                assert envelope.message_kind is MessageKind.ASYNC_REQUEST
                assert envelope.message_type == "MergeApprovalRequested"
                assert envelope.payload == {
                    "merge_request_id": merge_body["id"],
                    "domain": "customer",
                }
                assert envelope.correlation_id == audit.correlation_id == correlation_id
                assert envelope.request_id == audit.request_id == request_id

        assert api.client.portal is not None
        api.client.portal.call(verify)


def test_duplicate_flow_enforces_permission_scope_and_shape() -> None:
    with customer_api() as api:
        allow_duplicate_flow(api)
        source = create_customer(api, cpf="52998224725", legal_name="Maria Souza")
        candidate = create_customer(api, cpf="15350946056", legal_name="Maria Sousa")
        assert api.resolver.context is not None
        api.resolver.context = replace(api.resolver.context, permissions=frozenset({CUSTOMER_READ}))
        denied = api.client.post(
            f"/api/v1/customers/{source['id']}/merge-requests",
            json={
                "company_id": str(api.data.company_id),
                "candidate_customer_id": candidate["id"],
                "surviving_customer_id": source["id"],
                "reason": "Sem permissao.",
            },
            headers=api.headers,
        )
        assert denied.status_code == 403
        allow_duplicate_flow(api)
        assert (
            api.client.post(
                f"/api/v1/customers/{uuid4()}/duplicates/detect?company_id={api.data.company_id}",
                headers=api.headers,
            ).status_code
            == 404
        )
        assert (
            api.client.post(
                f"/api/v1/customers/{source['id']}/merge-requests",
                json={
                    "company_id": str(api.data.company_id),
                    "candidate_customer_id": source["id"],
                    "surviving_customer_id": source["id"],
                    "reason": "Mesmo cliente.",
                },
                headers=api.headers,
            ).status_code
            == 422
        )
        assert (
            api.client.post(
                f"/api/v1/customers/{source['id']}/merge-requests",
                json={
                    "company_id": str(api.data.company_id),
                    "candidate_customer_id": candidate["id"],
                    "surviving_customer_id": str(uuid4()),
                    "reason": "Sobrevivente fora do par.",
                },
                headers=api.headers,
            ).status_code
            == 422
        )
        assert duplicate_counts(api) == (0, 0, 0, 0)


def test_merge_request_is_company_scoped_and_duplicate_pair_is_rejected() -> None:
    with customer_api() as api:
        allow_duplicate_flow(api)
        source = create_customer(api, cpf="52998224725", legal_name="Maria Souza")
        candidate = create_customer(api, cpf="15350946056", legal_name="Maria Sousa")
        first = api.client.post(
            f"/api/v1/customers/{source['id']}/merge-requests",
            json={
                "company_id": str(api.data.company_id),
                "candidate_customer_id": candidate["id"],
                "surviving_customer_id": source["id"],
                "reason": "Primeira solicitacao.",
            },
            headers=api.headers,
        )
        duplicate = api.client.post(
            f"/api/v1/customers/{source['id']}/merge-requests",
            json={
                "company_id": str(api.data.company_id),
                "candidate_customer_id": candidate["id"],
                "surviving_customer_id": source["id"],
                "reason": "Duplicada.",
            },
            headers=api.headers,
        )
        assert first.status_code == 201
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "CUSTOMER_MERGE_REQUEST_CONFLICT"

        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            scopes=frozenset({Scope(ScopeType.COMPANY, api.data.other_company_id)}),
        )
        foreign = api.client.post(
            f"/api/v1/customers/{source['id']}/merge-requests",
            json={
                "company_id": str(api.data.other_company_id),
                "candidate_customer_id": candidate["id"],
                "surviving_customer_id": source["id"],
                "reason": "Fora do escopo.",
            },
            headers=api.headers,
        )
        assert foreign.status_code == 404


@pytest.mark.parametrize(
    ("component", "method"), [(AuditService, "record"), (OutboxService, "enqueue")]
)
def test_failed_merge_request_effect_rolls_back(
    monkeypatch: pytest.MonkeyPatch, component: type[Any], method: str
) -> None:
    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Forced merge request failure")

    with customer_api() as api:
        allow_duplicate_flow(api)
        source = create_customer(api, cpf="52998224725", legal_name="Maria Souza")
        candidate = create_customer(api, cpf="15350946056", legal_name="Maria Sousa")
        with monkeypatch.context() as patch:
            patch.setattr(component, method, fail)
            with pytest.raises(RuntimeError, match="Forced merge request failure"):
                api.client.post(
                    f"/api/v1/customers/{source['id']}/merge-requests",
                    json={
                        "company_id": str(api.data.company_id),
                        "candidate_customer_id": candidate["id"],
                        "surviving_customer_id": source["id"],
                        "reason": "Rollback fiscal.",
                    },
                    headers=api.headers,
                )
        assert duplicate_counts(api) == (0, 0, 0, 0)
