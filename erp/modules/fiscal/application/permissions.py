"""Official M11 permissions evaluated through public M1 contracts."""

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

FISCAL_NFE_READ = PermissionCode("fiscal.nfe.read")
FISCAL_NFE_ISSUE = PermissionCode("fiscal.nfe.issue")
FISCAL_NFE_CANCEL = PermissionCode("fiscal.nfe.cancel")
FISCAL_NFE_CORRECT = PermissionCode("fiscal.nfe.correct")
FISCAL_INBOUND_READ = PermissionCode("fiscal.inbound.read")
FISCAL_INBOUND_MANAGE = PermissionCode("fiscal.inbound.manage")


def fiscal_permission_registry() -> PermissionRegistry:
    specifications = (
        (FISCAL_NFE_READ, "Read fiscal documents and protocols", PermissionRiskLevel.HIGH),
        (FISCAL_NFE_ISSUE, "Issue NF-e and NFC-e", PermissionRiskLevel.CRITICAL),
        (FISCAL_NFE_CANCEL, "Cancel authorized fiscal documents", PermissionRiskLevel.CRITICAL),
        (FISCAL_NFE_CORRECT, "Register fiscal correction letters", PermissionRiskLevel.CRITICAL),
        (FISCAL_INBOUND_READ, "Read inbound fiscal documents", PermissionRiskLevel.HIGH),
        (
            FISCAL_INBOUND_MANAGE,
            "Upload and manifest inbound fiscal documents",
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


class FiscalAuthorization:
    """Fail-closed fiscal permission and company-scope policy."""

    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(fiscal_permission_registry())

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
    "FISCAL_INBOUND_MANAGE",
    "FISCAL_INBOUND_READ",
    "FISCAL_NFE_CANCEL",
    "FISCAL_NFE_CORRECT",
    "FISCAL_NFE_ISSUE",
    "FISCAL_NFE_READ",
    "FiscalAuthorization",
    "fiscal_permission_registry",
]
