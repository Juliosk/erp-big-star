"""Public company-scope gate for other bounded contexts."""

from dataclasses import replace
from uuid import UUID

from erp.modules.admin.application.corporate_ports import CompanyDirectory
from erp.modules.admin.application.security import SecurityContext
from erp.modules.admin.domain import CorporateStatus, ScopeType
from erp.platform.errors import ApplicationError


class CompanyAccessService:
    """Resolve hierarchy inside M1; branch visibility never grants company-wide writes."""

    def __init__(self, directory: CompanyDirectory) -> None:
        self._directory = directory

    async def require_company(
        self, context: SecurityContext, company_id: UUID, *, write: bool = False
    ) -> None:
        scopes = frozenset(
            scope
            for scope in context.scopes
            if not write or scope.scope_type in {ScopeType.COMPANY, ScopeType.GROUP}
        )
        tenant = replace(context, scopes=scopes).tenant_context()
        companies = await self._directory.list_companies(tenant, status=CorporateStatus.ACTIVE)
        if not any(company.id == company_id for company in companies):
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="The selected company was not found.",
                status_code=404,
            )


__all__ = ["CompanyAccessService"]
