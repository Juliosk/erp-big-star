"""PostgreSQL-backed acceptance test for GET /api/v1/admin/companies."""

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.modules.admin.application import ADMIN_COMPANY_READ, SecurityContext
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Company,
    EconomicGroup,
    Scope,
    ScopeType,
)
from erp.modules.admin.infrastructure import CompanyRepository, EconomicGroupRepository
from erp.platform.config import get_settings
from erp.platform.database import Database


class ResolverStub:
    def __init__(self, context: SecurityContext) -> None:
        self._context = context

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self._context if access_token == "integration-token" else None


def _cnpj(seed: int) -> str:
    base = f"56{seed:010d}"

    def digit(value: str, weights: tuple[int, ...]) -> str:
        remainder = (
            sum(int(number) * weight for number, weight in zip(value, weights, strict=True)) % 11
        )
        result = 11 - remainder
        return str(0 if result >= 10 else result)

    first = digit(base, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return base + first + digit(base + first, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))


@pytest.mark.integration
def test_get_companies_applies_rbac_and_database_tenant_filter() -> None:
    settings = get_settings()
    seed = uuid4().int % 10_000_000_000
    group = EconomicGroup.create(code=f"API_{uuid4().hex[:8]}", name="API Group")
    allowed = Company.create(
        group_id=group.id,
        code=f"ALW_{uuid4().hex[:8]}",
        legal_name="Allowed Company",
        trade_name=None,
        tax_id=_cnpj(seed),
        timezone="America/Sao_Paulo",
    )
    hidden = Company.create(
        group_id=group.id,
        code=f"HID_{uuid4().hex[:8]}",
        legal_name="Hidden Company",
        trade_name=None,
        tax_id=_cnpj((seed + 1) % 10_000_000_000),
        timezone="America/Sao_Paulo",
    )

    async def seed_database() -> None:
        database = Database(settings)
        try:
            async with database.session() as session, session.begin():
                await EconomicGroupRepository().add(session, group, actor_id=None)
                await CompanyRepository().add(session, allowed, actor_id=None)
                await CompanyRepository().add(session, hidden, actor_id=None)
        finally:
            await database.dispose()

    asyncio.run(seed_database())
    context = SecurityContext(
        principal=AuthenticatedPrincipal(uuid4(), uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=frozenset({ADMIN_COMPANY_READ}),
        scopes=frozenset({Scope(ScopeType.COMPANY, allowed.id)}),
    )

    with TestClient(
        create_app(settings, security_context_resolver=ResolverStub(context))
    ) as client:
        response = client.get(
            "/api/v1/admin/companies",
            headers={"Authorization": "Bearer integration-token"},
        )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(allowed.id)]
