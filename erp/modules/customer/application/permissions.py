"""Official customer permissions evaluated through the public M1 contract."""

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

CUSTOMER_READ = PermissionCode("crm.customer.read")
CUSTOMER_CREATE = PermissionCode("crm.customer.create")
CUSTOMER_UPDATE = PermissionCode("crm.customer.update")
CUSTOMER_MERGE = PermissionCode("crm.customer.merge")
CONSENT_MANAGE = PermissionCode("crm.consent.manage")


def customer_permission_registry() -> PermissionRegistry:
    return PermissionRegistry(
        Permission(
            code=code,
            description=description,
            risk_level=risk,
            data_classification=DataClassification.PERSONAL_DATA,
        )
        for code, description, risk in (
            (CUSTOMER_READ, "Read customer master", PermissionRiskLevel.LOW),
            (CUSTOMER_CREATE, "Create customer master", PermissionRiskLevel.HIGH),
            (CUSTOMER_UPDATE, "Update customer master", PermissionRiskLevel.HIGH),
            (CUSTOMER_MERGE, "Merge customer master records", PermissionRiskLevel.CRITICAL),
            (CONSENT_MANAGE, "Manage customer communication consents", PermissionRiskLevel.HIGH),
        )
    )


class CustomerAuthorization:
    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(customer_permission_registry())

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
    "CONSENT_MANAGE",
    "CUSTOMER_CREATE",
    "CUSTOMER_MERGE",
    "CUSTOMER_READ",
    "CUSTOMER_UPDATE",
    "CustomerAuthorization",
    "customer_permission_registry",
]
