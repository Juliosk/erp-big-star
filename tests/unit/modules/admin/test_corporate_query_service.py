"""Unit tests for company query authorization and tenant propagation."""

import asyncio
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.application import (
    ADMIN_COMPANY_READ,
    ListCompaniesService,
    SecurityContext,
)
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Company,
    CorporateStatus,
    PermissionCode,
    Scope,
    ScopeType,
    TenantContext,
)
from erp.platform.errors import ApplicationError


class CompanyDirectoryStub:
    def __init__(self, companies: tuple[Company, ...]) -> None:
        self.companies = companies
        self.context: TenantContext | None = None
        self.status: CorporateStatus | None = None

    async def list_companies(
        self,
        context: TenantContext,
        *,
        status: CorporateStatus | None = None,
    ) -> tuple[Company, ...]:
        self.context = context
        self.status = status
        return self.companies


def _company(group_id: UUID | None = None) -> Company:
    return Company.create(
        group_id=group_id or uuid4(),
        code="BIGSTAR",
        legal_name="Big Star Industria e Comercio Ltda",
        trade_name="Big Star",
        tax_id="04.252.011/0001-10",
        timezone="America/Sao_Paulo",
    )


def _context(
    *,
    permission: PermissionCode | None = ADMIN_COMPANY_READ,
    include_scope: bool = True,
) -> SecurityContext:
    user_id = uuid4()
    scopes = frozenset({Scope(ScopeType.COMPANY, uuid4())}) if include_scope else frozenset()
    permissions = frozenset({permission}) if permission is not None else frozenset()
    return SecurityContext(
        principal=AuthenticatedPrincipal(user_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=permissions,
        scopes=scopes,
    )


def test_list_companies_authorizes_and_propagates_exact_tenant_context() -> None:
    company = _company()
    directory = CompanyDirectoryStub((company,))
    context = _context()

    result = asyncio.run(
        ListCompaniesService(directory).execute(context, status=CorporateStatus.ACTIVE)
    )

    assert result[0].id == company.id
    assert result[0].tax_id == "04252011000110"
    assert directory.context == context.tenant_context()
    assert directory.status is CorporateStatus.ACTIVE


@pytest.mark.parametrize(
    ("context", "code"),
    [
        (_context(permission=None), "PERMISSION_FORBIDDEN"),
        (_context(include_scope=False), "SCOPE_FORBIDDEN"),
    ],
)
def test_list_companies_is_default_deny(context: SecurityContext, code: str) -> None:
    with pytest.raises(ApplicationError) as captured:
        asyncio.run(ListCompaniesService(CompanyDirectoryStub(())).execute(context))

    assert captured.value.code == code
