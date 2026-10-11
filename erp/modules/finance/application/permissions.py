"""Official M12 permissions evaluated through public M1 contracts."""

from uuid import UUID

from erp.modules.admin.contracts import (
    AuthorizationPolicy,
    CompanyAccessService,
    DataClassification,
    Permission,
    PermissionCode,
    PermissionRegistry,
    PermissionRiskLevel,
    SecurityContext,
    require_permission,
)

FINANCE_PAYABLE_READ = PermissionCode("finance.payable.read")
FINANCE_PAYABLE_CREATE = PermissionCode("finance.payable.create")
FINANCE_PAYABLE_APPROVE = PermissionCode("finance.payable.approve")
FINANCE_PAYABLE_ADJUST = PermissionCode("finance.payable.adjust")


def finance_permission_registry() -> PermissionRegistry:
    specifications = (
        (FINANCE_PAYABLE_READ, "Read payable provisions and titles", PermissionRiskLevel.HIGH),
        (FINANCE_PAYABLE_CREATE, "Create payable provisions and titles", PermissionRiskLevel.HIGH),
        (
            FINANCE_PAYABLE_APPROVE,
            "Approve payable provisions under the applicable authority",
            PermissionRiskLevel.CRITICAL,
        ),
        (
            FINANCE_PAYABLE_ADJUST,
            "Adjust payable amounts, due dates and blocks",
            PermissionRiskLevel.CRITICAL,
        ),
    )
    return PermissionRegistry(
        Permission(
            code=code,
            description=description,
            risk_level=risk,
            data_classification=DataClassification.RESTRICTED,
        )
        for code, description, risk in specifications
    )


class FinanceAuthorization:
    """Fail-closed M12 permission and company-scope policy."""

    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(finance_permission_registry())

    async def require(
        self,
        context: SecurityContext,
        company_id: UUID,
        permission: PermissionCode,
        *,
        write: bool = False,
    ) -> None:
        require_permission(policy=self._policy, context=context, permission=permission)
        await self._companies.require_company(context, company_id, write=write)


__all__ = [
    "FINANCE_PAYABLE_ADJUST",
    "FINANCE_PAYABLE_APPROVE",
    "FINANCE_PAYABLE_CREATE",
    "FINANCE_PAYABLE_READ",
    "FinanceAuthorization",
    "finance_permission_registry",
]
