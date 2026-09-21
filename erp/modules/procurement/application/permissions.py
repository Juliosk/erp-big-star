"""Official M6 permissions evaluated through public M1 contracts."""

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

PROCUREMENT_SUPPLIER_READ = PermissionCode("procurement.supplier.read")
PROCUREMENT_SUPPLIER_MANAGE = PermissionCode("procurement.supplier.manage")
PROCUREMENT_REQUISITION_CREATE = PermissionCode("procurement.requisition.create")
PROCUREMENT_REQUISITION_READ = PermissionCode("procurement.requisition.read")
PROCUREMENT_PURCHASE_ORDER_CREATE = PermissionCode("procurement.purchase_order.create")
PROCUREMENT_PURCHASE_ORDER_READ = PermissionCode("procurement.purchase_order.read")
PROCUREMENT_PURCHASE_ORDER_CHANGE = PermissionCode("procurement.purchase_order.change")
PROCUREMENT_PURCHASE_ORDER_SUBMIT = PermissionCode("procurement.purchase_order.submit")


def procurement_permission_registry() -> PermissionRegistry:
    specifications = (
        (
            PROCUREMENT_SUPPLIER_READ,
            "Read procurement suppliers and sites",
            PermissionRiskLevel.MEDIUM,
        ),
        (
            PROCUREMENT_SUPPLIER_MANAGE,
            "Create and update procurement suppliers",
            PermissionRiskLevel.HIGH,
        ),
        (
            PROCUREMENT_REQUISITION_CREATE,
            "Create purchase requisitions",
            PermissionRiskLevel.MEDIUM,
        ),
        (
            PROCUREMENT_REQUISITION_READ,
            "Read purchase requisitions",
            PermissionRiskLevel.MEDIUM,
        ),
        (
            PROCUREMENT_PURCHASE_ORDER_CREATE,
            "Create purchase orders",
            PermissionRiskLevel.HIGH,
        ),
        (
            PROCUREMENT_PURCHASE_ORDER_READ,
            "Read purchase orders",
            PermissionRiskLevel.MEDIUM,
        ),
        (
            PROCUREMENT_PURCHASE_ORDER_CHANGE,
            "Change mutable purchase orders",
            PermissionRiskLevel.HIGH,
        ),
        (
            PROCUREMENT_PURCHASE_ORDER_SUBMIT,
            "Submit purchase orders for approval",
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


class ProcurementAuthorization:
    """Fail-closed M6 authorization plus tenant scope enforcement."""

    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(procurement_permission_registry())

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
    "PROCUREMENT_PURCHASE_ORDER_CHANGE",
    "PROCUREMENT_PURCHASE_ORDER_CREATE",
    "PROCUREMENT_PURCHASE_ORDER_READ",
    "PROCUREMENT_PURCHASE_ORDER_SUBMIT",
    "PROCUREMENT_REQUISITION_CREATE",
    "PROCUREMENT_REQUISITION_READ",
    "PROCUREMENT_SUPPLIER_MANAGE",
    "PROCUREMENT_SUPPLIER_READ",
    "ProcurementAuthorization",
    "procurement_permission_registry",
]
