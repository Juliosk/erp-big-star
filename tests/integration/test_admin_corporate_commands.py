"""E2E database proof for idempotent corporate creation transactions."""

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from erp.apps.api.app import create_app
from erp.modules.admin.application import (
    ADMIN_BRANCH_CREATE,
    ADMIN_COMPANY_CREATE,
    SecurityContext,
)
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    EconomicGroup,
    Scope,
    ScopeType,
)
from erp.modules.admin.infrastructure import (
    BranchModel,
    CompanyModel,
    EconomicGroupRepository,
)
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.outbox import OutboxEventModel


class ResolverStub:
    def __init__(self, context: SecurityContext) -> None:
        self.context = context

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "command-token" else None


def _cnpj(seed: int) -> str:
    base = f"78{seed:010d}"

    def digit(value: str, weights: tuple[int, ...]) -> str:
        remainder = (
            sum(int(number) * weight for number, weight in zip(value, weights, strict=True)) % 11
        )
        result = 11 - remainder
        return str(0 if result >= 10 else result)

    first = digit(base, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return base + first + digit(base + first, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))


@pytest.mark.integration
def test_company_and_branch_creation_are_atomic_audited_outboxed_and_replayable() -> None:
    settings = get_settings()
    group = EconomicGroup.create(code=f"CMD_{uuid4().hex[:8]}", name="Command Group")
    actor_id = uuid4()
    seed = uuid4().int % 10_000_000_000

    async def seed_group() -> None:
        database = Database(settings)
        try:
            async with database.session() as session, session.begin():
                await EconomicGroupRepository().add(session, group, actor_id=actor_id)
        finally:
            await database.dispose()

    asyncio.run(seed_group())
    resolver = ResolverStub(
        SecurityContext(
            principal=AuthenticatedPrincipal(actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset({ADMIN_COMPANY_CREATE, ADMIN_BRANCH_CREATE}),
            scopes=frozenset({Scope(ScopeType.GROUP, group.id)}),
        )
    )
    company_key = str(uuid4())
    branch_key = str(uuid4())
    headers = {"Authorization": "Bearer command-token"}
    with TestClient(create_app(settings, security_context_resolver=resolver)) as client:
        company_body = {
            "group_id": str(group.id),
            "code": f"COMP_{uuid4().hex[:8]}",
            "legal_name": "Corporate Command Company",
            "trade_name": "Command Company",
            "tax_id": _cnpj(seed),
            "timezone": "America/Sao_Paulo",
        }
        created_company = client.post(
            "/api/v1/admin/companies",
            json=company_body,
            headers={**headers, "Idempotency-Key": company_key},
        )
        replayed_company = client.post(
            "/api/v1/admin/companies",
            json=company_body,
            headers={**headers, "Idempotency-Key": company_key},
        )
        conflicting_company = client.post(
            "/api/v1/admin/companies",
            json={**company_body, "legal_name": "Different Payload"},
            headers={**headers, "Idempotency-Key": company_key},
        )
        invalid_company = client.post(
            "/api/v1/admin/companies",
            json={**company_body, "tax_id": "00.000.000/0000-00"},
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )
        company_id = created_company.json()["company"]["id"]
        branch_body = {
            "company_id": company_id,
            "code": f"BR_{uuid4().hex[:8]}",
            "name": "Corporate Command Branch",
            "tax_id": _cnpj((seed + 1) % 10_000_000_000),
            "timezone": "America/Sao_Paulo",
        }
        created_branch = client.post(
            "/api/v1/admin/branches",
            json=branch_body,
            headers={**headers, "Idempotency-Key": branch_key},
        )
        replayed_branch = client.post(
            "/api/v1/admin/branches",
            json=branch_body,
            headers={**headers, "Idempotency-Key": branch_key},
        )

    assert created_company.status_code == replayed_company.status_code == 201
    assert created_branch.status_code == replayed_branch.status_code == 201
    assert conflicting_company.status_code == 409
    assert conflicting_company.json()["error"]["code"] == (
        "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"
    )
    assert invalid_company.status_code == 422
    assert invalid_company.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"
    assert created_company.headers["idempotency-replayed"] == "false"
    assert replayed_company.headers["idempotency-replayed"] == "true"
    assert created_branch.headers["idempotency-replayed"] == "false"
    assert replayed_branch.headers["idempotency-replayed"] == "true"
    assert created_company.json()["event_id"] == replayed_company.json()["event_id"]
    assert created_branch.json()["event_id"] == replayed_branch.json()["event_id"]

    async def assert_durable_records() -> None:
        database = Database(settings)
        company_uuid = UUID(company_id)
        branch_uuid = UUID(created_branch.json()["branch"]["id"])
        event_ids = {
            UUID(created_company.json()["event_id"]),
            UUID(created_branch.json()["event_id"]),
        }
        try:
            async with database.session() as session:
                company_count = await session.scalar(
                    select(func.count())
                    .select_from(CompanyModel)
                    .where(CompanyModel.id == company_uuid)
                )
                branch_count = await session.scalar(
                    select(func.count())
                    .select_from(BranchModel)
                    .where(BranchModel.id == branch_uuid)
                )
                outbox = (
                    await session.scalars(
                        select(OutboxEventModel).where(OutboxEventModel.event_id.in_(event_ids))
                    )
                ).all()
                audit_count = await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(AuditEventModel.entity_id.in_({company_uuid, branch_uuid}))
                )
            assert company_count == 1
            assert branch_count == 1
            assert {event.event_type for event in outbox} == {"CompanyCreated", "BranchCreated"}
            assert all(event.published_at is None for event in outbox)
            assert audit_count == 2
        finally:
            await database.dispose()

    asyncio.run(assert_durable_records())


@pytest.mark.integration
def test_branch_scope_cannot_create_a_sibling_branch() -> None:
    settings = get_settings()
    resolver = ResolverStub(
        SecurityContext(
            principal=AuthenticatedPrincipal(uuid4(), uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset({ADMIN_BRANCH_CREATE}),
            scopes=frozenset({Scope(ScopeType.BRANCH, uuid4())}),
        )
    )
    with TestClient(create_app(settings, security_context_resolver=resolver)) as client:
        response = client.post(
            "/api/v1/admin/branches",
            json={
                "company_id": str(uuid4()),
                "code": "NO_SIBLING",
                "name": "Forbidden Sibling",
                "tax_id": _cnpj(uuid4().int % 10_000_000_000),
                "timezone": "America/Sao_Paulo",
            },
            headers={
                "Authorization": "Bearer command-token",
                "Idempotency-Key": str(uuid4()),
            },
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
