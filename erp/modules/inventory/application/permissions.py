"""Official inventory permissions evaluated through the public M1 contract."""

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

INVENTORY_BALANCE_READ = PermissionCode("inventory.balance.read")
INVENTORY_RESERVATION_MANAGE = PermissionCode("inventory.reservation.manage")
INVENTORY_TRANSFER_CREATE = PermissionCode("inventory.transfer.create")
INVENTORY_ADJUSTMENT_CREATE = PermissionCode("inventory.adjustment.create")
INVENTORY_ADJUSTMENT_CONFIRM = PermissionCode("inventory.adjustment.confirm")
INVENTORY_CYCLE_COUNT_MANAGE = PermissionCode("inventory.cycle_count.manage")


def inventory_permission_registry() -> PermissionRegistry:
    return PermissionRegistry(
        Permission(
            code=code,
            description=description,
            risk_level=risk,
            data_classification=DataClassification.CONFIDENTIAL,
        )
        for code, description, risk in (
            (INVENTORY_BALANCE_READ, "Read inventory balances", PermissionRiskLevel.LOW),
            (
                INVENTORY_RESERVATION_MANAGE,
                "Manage inventory reservations",
                PermissionRiskLevel.CRITICAL,
            ),
            (INVENTORY_TRANSFER_CREATE, "Create inventory transfers", PermissionRiskLevel.HIGH),
            (INVENTORY_ADJUSTMENT_CREATE, "Create inventory adjustments", PermissionRiskLevel.HIGH),
            (
                INVENTORY_ADJUSTMENT_CONFIRM,
                "Confirm inventory adjustments",
                PermissionRiskLevel.CRITICAL,
            ),
            (
                INVENTORY_CYCLE_COUNT_MANAGE,
                "Manage inventory cycle counts",
                PermissionRiskLevel.HIGH,
            ),
        )
    )


class InventoryAuthorization:
    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(inventory_permission_registry())

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
    "INVENTORY_ADJUSTMENT_CONFIRM",
    "INVENTORY_ADJUSTMENT_CREATE",
    "INVENTORY_BALANCE_READ",
    "INVENTORY_CYCLE_COUNT_MANAGE",
    "INVENTORY_RESERVATION_MANAGE",
    "INVENTORY_TRANSFER_CREATE",
    "InventoryAuthorization",
    "inventory_permission_registry",
]
