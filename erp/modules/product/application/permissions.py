"""Official product permissions evaluated by the public M1 authorization contract."""

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

PRODUCT_READ = PermissionCode("product.product.read")
PRODUCT_CREATE = PermissionCode("product.product.create")
PRODUCT_UPDATE = PermissionCode("product.product.update")
PRODUCT_ACTIVATE = PermissionCode("product.product.activate")
PRODUCT_DISCONTINUE = PermissionCode("product.product.discontinue")


def product_permission_registry() -> PermissionRegistry:
    return PermissionRegistry(
        Permission(
            code=code,
            description=description,
            risk_level=risk,
            data_classification=DataClassification.CONFIDENTIAL,
        )
        for code, description, risk in (
            (PRODUCT_READ, "Read product master", PermissionRiskLevel.LOW),
            (PRODUCT_CREATE, "Create product master", PermissionRiskLevel.HIGH),
            (PRODUCT_UPDATE, "Update product master", PermissionRiskLevel.HIGH),
            (PRODUCT_ACTIVATE, "Activate product master", PermissionRiskLevel.HIGH),
            (PRODUCT_DISCONTINUE, "Discontinue product master", PermissionRiskLevel.HIGH),
        )
    )


class ProductAuthorization:
    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(product_permission_registry())

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
    "PRODUCT_ACTIVATE",
    "PRODUCT_CREATE",
    "PRODUCT_DISCONTINUE",
    "PRODUCT_READ",
    "PRODUCT_UPDATE",
    "ProductAuthorization",
    "product_permission_registry",
]
