"""Corporate read use cases independent from HTTP and SQLAlchemy."""

from erp.modules.admin.application.authorization import require_permission
from erp.modules.admin.application.corporate_dto import CompanyView
from erp.modules.admin.application.corporate_permissions import (
    ADMIN_COMPANY_READ,
    corporate_permission_registry,
)
from erp.modules.admin.application.corporate_ports import CompanyDirectory
from erp.modules.admin.application.security import SecurityContext
from erp.modules.admin.domain import AuthorizationPolicy, CorporateStatus


class ListCompaniesService:
    """Return only companies visible through the actor's fresh RBAC context."""

    def __init__(
        self,
        directory: CompanyDirectory,
        policy: AuthorizationPolicy | None = None,
    ) -> None:
        self._directory = directory
        self._policy = policy or AuthorizationPolicy(corporate_permission_registry())

    async def execute(
        self,
        context: SecurityContext,
        *,
        status: CorporateStatus | None = None,
    ) -> tuple[CompanyView, ...]:
        require_permission(
            policy=self._policy,
            context=context,
            permission=ADMIN_COMPANY_READ,
        )
        companies = await self._directory.list_companies(context.tenant_context(), status=status)
        return tuple(CompanyView.from_domain(company) for company in companies)


__all__ = ["ListCompaniesService"]
