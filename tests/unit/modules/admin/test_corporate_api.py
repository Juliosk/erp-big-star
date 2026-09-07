"""HTTP contract tests for the first official business endpoint."""

from uuid import uuid4

from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
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
    Scope,
    ScopeType,
    TenantContext,
)
from erp.platform.config import Settings
from erp.platform.database import ManagedDatabase


class AvailableDatabase(ManagedDatabase):
    async def ping(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


class DirectoryStub:
    def __init__(self, company: Company) -> None:
        self.company = company

    async def list_companies(
        self,
        context: TenantContext,
        *,
        status: CorporateStatus | None = None,
    ) -> tuple[Company, ...]:
        if status is not None and self.company.status is not status:
            return ()
        return (self.company,)


class ResolverStub:
    def __init__(self, context: SecurityContext | None) -> None:
        self.context = context

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "valid-token" else None


def _security_context(*, permitted: bool = True) -> SecurityContext:
    company_id = uuid4()
    return SecurityContext(
        principal=AuthenticatedPrincipal(uuid4(), uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=frozenset({ADMIN_COMPANY_READ}) if permitted else frozenset(),
        scopes=frozenset({Scope(ScopeType.COMPANY, company_id)}),
    )


def _client(context: SecurityContext | None) -> TestClient:
    company = Company.create(
        group_id=uuid4(),
        code="BIGSTAR",
        legal_name="Big Star Industria e Comercio Ltda",
        trade_name="Big Star",
        tax_id="04.252.011/0001-10",
        timezone="America/Sao_Paulo",
    )
    app = create_app(
        Settings.model_validate({"environment": "test"}),
        AvailableDatabase(),
        company_query_service=ListCompaniesService(DirectoryStub(company)),
        security_context_resolver=ResolverStub(context),
    )
    return TestClient(app)


def test_get_companies_returns_the_official_contract() -> None:
    with _client(_security_context()) as client:
        response = client.get(
            "/api/v1/admin/companies?status=ACTIVE",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200
    assert response.json()["items"][0] == {
        "id": response.json()["items"][0]["id"],
        "group_id": response.json()["items"][0]["group_id"],
        "code": "BIGSTAR",
        "legal_name": "Big Star Industria e Comercio Ltda",
        "trade_name": "Big Star",
        "tax_id": "04252011000110",
        "timezone": "America/Sao_Paulo",
        "status": "ACTIVE",
        "version": 1,
    }


def test_get_companies_requires_bearer_authentication() -> None:
    correlation_id = str(uuid4())
    with _client(_security_context()) as client:
        response = client.get(
            "/api/v1/admin/companies",
            headers={"X-Correlation-ID": correlation_id},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert response.json()["error"]["correlation_id"] == correlation_id


def test_get_companies_returns_rbac_failure_through_error_contract() -> None:
    with _client(_security_context(permitted=False)) as client:
        response = client.get(
            "/api/v1/admin/companies",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_FORBIDDEN"
    assert response.json()["error"]["details"] == []
