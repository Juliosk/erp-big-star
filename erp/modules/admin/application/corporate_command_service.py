"""RBAC-protected corporate creation use cases."""

from erp.modules.admin.application.authorization import require_permission
from erp.modules.admin.application.corporate_command_dto import (
    BranchCreationResult,
    CompanyCreationResult,
    CreateBranchCommand,
    CreateCompanyCommand,
)
from erp.modules.admin.application.corporate_command_ports import CorporateCommandStore
from erp.modules.admin.application.corporate_permissions import (
    ADMIN_BRANCH_CREATE,
    ADMIN_COMPANY_CREATE,
    corporate_permission_registry,
)
from erp.modules.admin.application.security import SecurityContext
from erp.modules.admin.domain import AuthorizationPolicy, Scope, ScopeType


class CorporateCreationService:
    """Authorize commands before entering their atomic persistence boundary."""

    def __init__(
        self,
        store: CorporateCommandStore,
        policy: AuthorizationPolicy | None = None,
    ) -> None:
        self._store = store
        self._policy = policy or AuthorizationPolicy(corporate_permission_registry())

    async def create_company(
        self,
        context: SecurityContext,
        command: CreateCompanyCommand,
    ) -> CompanyCreationResult:
        require_permission(
            policy=self._policy,
            context=context,
            permission=ADMIN_COMPANY_CREATE,
            scope=Scope(ScopeType.GROUP, command.group_id),
        )
        return await self._store.create_company(command, context.tenant_context())

    async def create_branch(
        self,
        context: SecurityContext,
        command: CreateBranchCommand,
    ) -> BranchCreationResult:
        require_permission(
            policy=self._policy,
            context=context,
            permission=ADMIN_BRANCH_CREATE,
        )
        return await self._store.create_branch(command, context.tenant_context())


__all__ = ["CorporateCreationService"]
