"""RBAC-protected group, branch and company-selector queries."""

from uuid import UUID

from erp.modules.admin.application.authorization import require_permission
from erp.modules.admin.application.corporate_dto import (
    BranchView,
    CompanySelectorCompany,
    CompanySelectorGroup,
    CompanySelectorView,
    CompanyView,
    EconomicGroupView,
)
from erp.modules.admin.application.corporate_permissions import (
    ADMIN_BRANCH_READ,
    ADMIN_COMPANY_READ,
    ADMIN_ECONOMIC_GROUP_READ,
    corporate_permission_registry,
)
from erp.modules.admin.application.corporate_ports import CorporateDirectory
from erp.modules.admin.application.security import SecurityContext
from erp.modules.admin.domain import AuthorizationPolicy, CorporateStatus, PermissionCode
from erp.platform.errors import ApplicationError


class CorporateHierarchyService:
    """Expose scope-filtered hierarchy queries for administration and selection."""

    def __init__(
        self,
        directory: CorporateDirectory,
        policy: AuthorizationPolicy | None = None,
    ) -> None:
        self._directory = directory
        self._policy = policy or AuthorizationPolicy(corporate_permission_registry())

    async def list_groups(
        self,
        context: SecurityContext,
        *,
        status: CorporateStatus | None = None,
    ) -> tuple[EconomicGroupView, ...]:
        self._authorize(context, ADMIN_ECONOMIC_GROUP_READ)
        groups = await self._directory.list_groups(context.tenant_context(), status=status)
        return tuple(EconomicGroupView.from_domain(group) for group in groups)

    async def list_branches(
        self,
        context: SecurityContext,
        *,
        company_id: UUID | None = None,
        status: CorporateStatus | None = None,
    ) -> tuple[BranchView, ...]:
        self._authorize(context, ADMIN_BRANCH_READ)
        branches = await self._directory.list_branches(context.tenant_context(), status=status)
        if company_id is not None:
            branches = tuple(branch for branch in branches if branch.company_id == company_id)
        return tuple(BranchView.from_domain(branch) for branch in branches)

    async def get_company(
        self,
        context: SecurityContext,
        company_id: UUID,
    ) -> CompanyView:
        self._authorize(context, ADMIN_COMPANY_READ)
        companies = await self._directory.list_companies(context.tenant_context())
        company = next((item for item in companies if item.id == company_id), None)
        if company is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="The requested company was not found.",
                status_code=404,
            )
        return CompanyView.from_domain(company)

    async def company_selector(self, context: SecurityContext) -> CompanySelectorView:
        self._authorize(context, ADMIN_ECONOMIC_GROUP_READ)
        self._authorize(context, ADMIN_COMPANY_READ)
        self._authorize(context, ADMIN_BRANCH_READ)
        tenant = context.tenant_context()
        groups = await self._directory.list_groups(tenant, status=CorporateStatus.ACTIVE)
        companies = await self._directory.list_companies(tenant, status=CorporateStatus.ACTIVE)
        branches = await self._directory.list_branches(tenant, status=CorporateStatus.ACTIVE)
        group_nodes = tuple(
            CompanySelectorGroup(
                group=EconomicGroupView.from_domain(group),
                companies=tuple(
                    CompanySelectorCompany(
                        company=CompanyView.from_domain(company),
                        branches=tuple(
                            BranchView.from_domain(branch)
                            for branch in branches
                            if branch.company_id == company.id
                        ),
                    )
                    for company in companies
                    if company.group_id == group.id
                ),
            )
            for group in groups
        )
        return CompanySelectorView(groups=group_nodes)

    def _authorize(self, context: SecurityContext, permission: PermissionCode) -> None:
        require_permission(
            policy=self._policy,
            context=context,
            permission=permission,
        )


__all__ = ["CorporateHierarchyService"]
