"""Production permissions evaluated through public M1 contracts."""

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

PRODUCTION_ENGINEERING_READ = PermissionCode("production.engineering.read")
PRODUCTION_ENGINEERING_WRITE = PermissionCode("production.engineering.write")
PRODUCTION_PLANNING_READ = PermissionCode("production.planning.read")
PRODUCTION_PLANNING_RUN = PermissionCode("production.planning.run")
PRODUCTION_SHOP_FLOOR_READ = PermissionCode("production.shop_floor.read")
PRODUCTION_SHOP_FLOOR_EXECUTE = PermissionCode("production.shop_floor.execute")


def production_permission_registry() -> PermissionRegistry:
    specifications = (
        (
            PRODUCTION_ENGINEERING_READ,
            "Read production BOMs, engineering versions and routings",
            PermissionRiskLevel.MEDIUM,
        ),
        (
            PRODUCTION_ENGINEERING_WRITE,
            "Create and version production BOMs, work centers and routings",
            PermissionRiskLevel.HIGH,
        ),
        (
            PRODUCTION_PLANNING_READ,
            "Read material requirements and production plans",
            PermissionRiskLevel.HIGH,
        ),
        (
            PRODUCTION_PLANNING_RUN,
            "Execute MRP planning and release planned orders",
            PermissionRiskLevel.CRITICAL,
        ),
        (
            PRODUCTION_SHOP_FLOOR_READ,
            "Read production orders and shop-floor progress",
            PermissionRiskLevel.HIGH,
        ),
        (
            PRODUCTION_SHOP_FLOOR_EXECUTE,
            "Report production, consumption and scrap on the shop floor",
            PermissionRiskLevel.CRITICAL,
        ),
    )
    return PermissionRegistry(
        Permission(
            code=code,
            description=description,
            risk_level=risk,
            data_classification=DataClassification.CONFIDENTIAL,
        )
        for code, description, risk in specifications
    )


class ProductionAuthorization:
    """Fail-closed permission checks combined with company scope."""

    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(production_permission_registry())

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
    "PRODUCTION_ENGINEERING_READ",
    "PRODUCTION_ENGINEERING_WRITE",
    "PRODUCTION_PLANNING_READ",
    "PRODUCTION_PLANNING_RUN",
    "PRODUCTION_SHOP_FLOOR_EXECUTE",
    "PRODUCTION_SHOP_FLOOR_READ",
    "ProductionAuthorization",
    "production_permission_registry",
]

