"""Official M10 WMS permissions evaluated through the public M1 contract."""

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

WMS_PICK_EXECUTE = PermissionCode("wms.pick.execute")
WMS_PACK_EXECUTE = PermissionCode("wms.pack.execute")
WMS_DISPATCH_EXECUTE = PermissionCode("wms.dispatch.execute")
WMS_LABEL_REPRINT = PermissionCode("wms.label.reprint")
WMS_SHORTAGE_OVERRIDE = PermissionCode("wms.shortage.override")


def wms_permission_registry() -> PermissionRegistry:
    return PermissionRegistry(
        Permission(
            code=code,
            description=description,
            risk_level=risk,
            data_classification=DataClassification.CONFIDENTIAL,
        )
        for code, description, risk in (
            (WMS_PICK_EXECUTE, "Execute WMS picking tasks", PermissionRiskLevel.HIGH),
            (WMS_PACK_EXECUTE, "Execute WMS packing tasks", PermissionRiskLevel.HIGH),
            (WMS_DISPATCH_EXECUTE, "Execute WMS dispatch operations", PermissionRiskLevel.HIGH),
            (WMS_LABEL_REPRINT, "Reprint WMS labels", PermissionRiskLevel.CRITICAL),
            (
                WMS_SHORTAGE_OVERRIDE,
                "Override WMS shortages during fulfillment",
                PermissionRiskLevel.CRITICAL,
            ),
        )
    )


class WmsAuthorization:
    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(wms_permission_registry())

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
    "WMS_DISPATCH_EXECUTE",
    "WMS_LABEL_REPRINT",
    "WMS_PACK_EXECUTE",
    "WMS_PICK_EXECUTE",
    "WMS_SHORTAGE_OVERRIDE",
    "WmsAuthorization",
    "wms_permission_registry",
]

