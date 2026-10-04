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
PROCUREMENT_REQUISITION_READ = PermissionCode("procurement.requisition.read")
PROCUREMENT_REQUISITION_MANAGE = PermissionCode("procurement.requisition.manage")
PROCUREMENT_ORDER_READ = PermissionCode("procurement.order.read")
PROCUREMENT_ORDER_MANAGE = PermissionCode("procurement.order.manage")
PROCUREMENT_RECEIPT_READ = PermissionCode("procurement.receipt.read")
PROCUREMENT_RECEIPT_MANAGE = PermissionCode("procurement.receipt.manage")


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
            PROCUREMENT_REQUISITION_READ,
            "Read purchase requisitions",
            PermissionRiskLevel.MEDIUM,
        ),
        (
            PROCUREMENT_REQUISITION_MANAGE,
            "Create and transition purchase requisitions",
            PermissionRiskLevel.HIGH,
        ),
        (
            PROCUREMENT_ORDER_READ,
            "Read purchase orders",
            PermissionRiskLevel.MEDIUM,
        ),
        (
            PROCUREMENT_ORDER_MANAGE,
            "Create and transition purchase orders",
            PermissionRiskLevel.HIGH,
        ),
        (
            PROCUREMENT_RECEIPT_READ,
            "Read physical goods receipts",
            PermissionRiskLevel.MEDIUM,
        ),
        (
            PROCUREMENT_RECEIPT_MANAGE,
            "Create and transition physical goods receipts",
            PermissionRiskLevel.HIGH,
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
    "PROCUREMENT_ORDER_MANAGE",
    "PROCUREMENT_ORDER_READ",
    "PROCUREMENT_RECEIPT_MANAGE",
    "PROCUREMENT_RECEIPT_READ",
    "PROCUREMENT_REQUISITION_MANAGE",
    "PROCUREMENT_REQUISITION_READ",
    "PROCUREMENT_SUPPLIER_MANAGE",
    "PROCUREMENT_SUPPLIER_READ",
    "ProcurementAuthorization",
    "procurement_permission_registry",
]
