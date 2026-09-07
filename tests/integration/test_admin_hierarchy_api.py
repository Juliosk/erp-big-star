"""E2E contract for group, branch and Company Selector APIs."""

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.modules.admin.application import (
    ADMIN_BRANCH_READ,
    ADMIN_COMPANY_READ,
    ADMIN_ECONOMIC_GROUP_READ,
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
from erp.platform.config import get_settings
from erp.platform.database import Database


class ResolverStub:
    def __init__(self, context: SecurityContext) -> None:
        self.context = context

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "selector-token" else None


def _cnpj(prefix: str, seed: int) -> str:
    base = f"{prefix}{seed:010d}"

    def digit(value: str, weights: tuple[int, ...]) -> str:
        remainder = (
            sum(int(number) * weight for number, weight in zip(value, weights, strict=True)) % 11
        )
        result = 11 - remainder
        return str(0 if result >= 10 else result)

    first = digit(base, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return base + first + digit(base + first, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))


@pytest.mark.integration
def test_complementary_apis_never_expose_sibling_company_hierarchies() -> None:
    settings = get_settings()
    seed = uuid4().int % 10_000_000_000
    group_a = EconomicGroup.create(code=f"SA_{uuid4().hex[:8]}", name="Selector A")
    group_b = EconomicGroup.create(code=f"SB_{uuid4().hex[:8]}", name="Selector B")
    company_a = Company.create(
        group_id=group_a.id,
        code=f"SCA_{uuid4().hex[:8]}",
        legal_name="Selector Company A",
        trade_name=None,
        tax_id=_cnpj("23", seed),
        timezone="America/Sao_Paulo",
    )
    company_b = Company.create(
        group_id=group_b.id,
        code=f"SCB_{uuid4().hex[:8]}",
        legal_name="Selector Company B",
        trade_name=None,
        tax_id=_cnpj("24", seed),
        timezone="America/Sao_Paulo",
    )
    branch_a = Branch.create(
        company_id=company_a.id,
        code=f"SBA_{uuid4().hex[:8]}",
        name="Selector Branch A",
        tax_id=_cnpj("25", seed),
        timezone="America/Sao_Paulo",
    )
    branch_b = Branch.create(
        company_id=company_b.id,
        code=f"SBB_{uuid4().hex[:8]}",
        name="Selector Branch B",
        tax_id=_cnpj("26", seed),
        timezone="America/Sao_Paulo",
    )

    async def seed_database() -> None:
        database = Database(settings)
        try:
            async with database.session() as session, session.begin():
                for group in (group_a, group_b):
                    await EconomicGroupRepository().add(session, group, actor_id=None)
                for company in (company_a, company_b):
                    await CompanyRepository().add(session, company, actor_id=None)
                for branch in (branch_a, branch_b):
                    await BranchRepository().add(session, branch, actor_id=None)
        finally:
            await database.dispose()

    asyncio.run(seed_database())
    resolver = ResolverStub(
        SecurityContext(
            principal=AuthenticatedPrincipal(uuid4(), uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset(
                {ADMIN_ECONOMIC_GROUP_READ, ADMIN_COMPANY_READ, ADMIN_BRANCH_READ}
            ),
            scopes=frozenset({Scope(ScopeType.COMPANY, company_a.id)}),
        )
    )
    headers = {"Authorization": "Bearer selector-token"}
    with TestClient(create_app(settings, security_context_resolver=resolver)) as client:
        groups = client.get("/api/v1/admin/economic-groups", headers=headers)
        branches = client.get("/api/v1/admin/branches", headers=headers)
        filtered_branches = client.get(
            f"/api/v1/admin/branches?company_id={company_b.id}",
            headers=headers,
        )
        company = client.get(f"/api/v1/admin/companies/{company_a.id}", headers=headers)
        hidden_company = client.get(f"/api/v1/admin/companies/{company_b.id}", headers=headers)
        selector = client.get("/api/v1/admin/company-selector", headers=headers)

    assert [item["id"] for item in groups.json()["items"]] == [str(group_a.id)]
    assert [item["id"] for item in branches.json()["items"]] == [str(branch_a.id)]
    assert filtered_branches.json() == {"items": []}
    assert company.status_code == 200
    assert company.headers["etag"] == '"1"'
    assert hidden_company.status_code == 404
    assert hidden_company.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    selector_groups = selector.json()["groups"]
    assert len(selector_groups) == 1
    assert selector_groups[0]["group"]["id"] == str(group_a.id)
    assert [node["company"]["id"] for node in selector_groups[0]["companies"]] == [
        str(company_a.id)
    ]
    assert [item["id"] for item in selector_groups[0]["companies"][0]["branches"]] == [
        str(branch_a.id)
    ]
