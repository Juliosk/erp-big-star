"""PostgreSQL E2E proofs for If-Match protected corporate updates."""

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from erp.apps.api.app import create_app
from erp.modules.admin.application import (
    ADMIN_BRANCH_UPDATE,
    ADMIN_COMPANY_UPDATE,
    SecurityContext,
)
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Branch,
    Company,
    EconomicGroup,
    Scope,
    ScopeType,
)
from erp.modules.admin.infrastructure import (
    BranchRepository,
    CompanyRepository,
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
        return self.context if access_token == "update-token" else None


def _cnpj(seed: int) -> str:
    base = f"91{seed:010d}"

    def digit(value: str, weights: tuple[int, ...]) -> str:
        remainder = (
            sum(int(number) * weight for number, weight in zip(value, weights, strict=True)) % 11
        )
        result = 11 - remainder
        return str(0 if result >= 10 else result)

    first = digit(base, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return base + first + digit(base + first, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))


@pytest.mark.integration
def test_company_and_branch_patch_require_and_enforce_current_version() -> None:
    settings = get_settings()
    seed = uuid4().int % 10_000_000_000
    actor_id = uuid4()
    group = EconomicGroup.create(code=f"UPD_{uuid4().hex[:8]}", name="Update Group")
    company = Company.create(
        group_id=group.id,
        code=f"UC_{uuid4().hex[:8]}",
        legal_name="Original Company",
        trade_name="Original Trade",
        tax_id=_cnpj(seed),
        timezone="America/Sao_Paulo",
    )
    branch = Branch.create(
        company_id=company.id,
        code=f"UB_{uuid4().hex[:8]}",
        name="Original Branch",
        tax_id=_cnpj((seed + 1) % 10_000_000_000),
        timezone="America/Sao_Paulo",
    )

    async def seed_database() -> None:
        database = Database(settings)
        try:
            async with database.session() as session, session.begin():
                await EconomicGroupRepository().add(session, group, actor_id=actor_id)
                await CompanyRepository().add(session, company, actor_id=actor_id)
                await BranchRepository().add(session, branch, actor_id=actor_id)
        finally:
            await database.dispose()

    asyncio.run(seed_database())
    resolver = ResolverStub(
        SecurityContext(
            principal=AuthenticatedPrincipal(actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset({ADMIN_COMPANY_UPDATE, ADMIN_BRANCH_UPDATE}),
            scopes=frozenset({Scope(ScopeType.GROUP, group.id)}),
        )
    )
    headers = {"Authorization": "Bearer update-token"}
    with TestClient(create_app(settings, security_context_resolver=resolver)) as client:
        updated_company = client.patch(
            f"/api/v1/admin/companies/{company.id}",
            json={"legal_name": "Updated Company", "trade_name": None},
            headers={**headers, "If-Match": '"1"'},
        )
        stale_company = client.patch(
            f"/api/v1/admin/companies/{company.id}",
            json={"legal_name": "Stale Company"},
            headers={**headers, "If-Match": '"1"'},
        )
        missing_precondition = client.patch(
            f"/api/v1/admin/companies/{company.id}",
            json={"legal_name": "Missing Version"},
            headers=headers,
        )
        invalid_precondition = client.patch(
            f"/api/v1/admin/companies/{company.id}",
            json={"legal_name": "Invalid Version"},
            headers={**headers, "If-Match": "1"},
        )
        empty_patch = client.patch(
            f"/api/v1/admin/companies/{company.id}",
            json={},
            headers={**headers, "If-Match": '"2"'},
        )
        updated_branch = client.patch(
            f"/api/v1/admin/branches/{branch.id}",
            json={"name": "Updated Branch", "status": "INACTIVE"},
            headers={**headers, "If-Match": '"1"'},
        )

    assert updated_company.status_code == 200
    assert updated_company.headers["etag"] == '"2"'
    assert updated_company.json()["company"]["version"] == 2
    assert updated_company.json()["company"]["trade_name"] is None
    assert stale_company.status_code == 409
    assert stale_company.json()["error"]["code"] == "VERSION_CONFLICT"
    assert missing_precondition.status_code == 428
    assert missing_precondition.json()["error"]["code"] == "PRECONDITION_REQUIRED"
    assert invalid_precondition.status_code == 400
    assert invalid_precondition.json()["error"]["code"] == "INVALID_IF_MATCH"
    assert empty_patch.status_code == 422
    assert empty_patch.json()["error"]["code"] == "EMPTY_PATCH"
    assert updated_branch.status_code == 200
    assert updated_branch.headers["etag"] == '"2"'
    assert updated_branch.json()["branch"]["status"] == "INACTIVE"

    async def assert_durable_evidence() -> None:
        database = Database(settings)
        try:
            async with database.session() as session:
                stored_company = await CompanyRepository().get(session, company.id)
                stored_branch = await BranchRepository().get(session, branch.id)
                events = (
                    await session.scalars(
                        select(OutboxEventModel).where(
                            OutboxEventModel.event_id.in_(
                                {
                                    UUID(updated_company.json()["event_id"]),
                                    UUID(updated_branch.json()["event_id"]),
                                }
                            )
                        )
                    )
                ).all()
                audits = (
                    await session.scalars(
                        select(AuditEventModel).where(
                            AuditEventModel.entity_id.in_({company.id, branch.id}),
                            AuditEventModel.operation == "UPDATE",
                        )
                    )
                ).all()
            assert stored_company is not None
            assert stored_company.legal_name == "Updated Company"
            assert stored_company.version == 2
            assert stored_branch is not None
            assert stored_branch.name == "Updated Branch"
            assert stored_branch.version == 2
            assert {event.event_type for event in events} == {"CompanyUpdated", "BranchUpdated"}
            assert len(audits) == 2
        finally:
            await database.dispose()

    asyncio.run(assert_durable_evidence())
