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

# Physical catalogue permissions are intentionally separate from future stock
# mutation permissions.  Every operation still requires an explicit company
# scope through ``InventoryAuthorization``.
INVENTORY_WAREHOUSE_READ = PermissionCode("inventory.warehouse.read")
INVENTORY_WAREHOUSE_CREATE = PermissionCode("inventory.warehouse.create")
INVENTORY_LOCATION_READ = PermissionCode("inventory.location.read")
INVENTORY_LOCATION_CREATE = PermissionCode("inventory.location.create")
INVENTORY_POOL_READ = PermissionCode("inventory.pool.read")
INVENTORY_POOL_CREATE = PermissionCode("inventory.pool.create")
INVENTORY_LOT_READ = PermissionCode("inventory.lot.read")
INVENTORY_LOT_CREATE = PermissionCode("inventory.lot.create")


def inventory_permission_registry() -> PermissionRegistry:
    """Return the original M5 movement permission registry.

    The physical-catalogue permissions are exposed through
    :func:`inventory_catalogue_permission_registry` so existing M5 consumers
    that snapshot the original registry remain compatible while the 062/063
    slice gets an explicit policy.
    """
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


def inventory_catalogue_permission_registry() -> PermissionRegistry:
    """Return movement and physical-catalogue permissions for 062/063."""
    registry = inventory_permission_registry()
    for code, description, risk in (
        (INVENTORY_WAREHOUSE_READ, "Read inventory warehouses", PermissionRiskLevel.LOW),
        (INVENTORY_WAREHOUSE_CREATE, "Create inventory warehouses", PermissionRiskLevel.HIGH),
        (INVENTORY_LOCATION_READ, "Read inventory locations", PermissionRiskLevel.LOW),
        (INVENTORY_LOCATION_CREATE, "Create inventory locations", PermissionRiskLevel.HIGH),
        (INVENTORY_POOL_READ, "Read inventory pools", PermissionRiskLevel.LOW),
        (INVENTORY_POOL_CREATE, "Create inventory pools", PermissionRiskLevel.HIGH),
        (INVENTORY_LOT_READ, "Read inventory lots", PermissionRiskLevel.LOW),
        (INVENTORY_LOT_CREATE, "Create inventory lots", PermissionRiskLevel.HIGH),
    ):
        registry.register(
            Permission(
                code=code,
                description=description,
                risk_level=risk,
                data_classification=DataClassification.CONFIDENTIAL,
            )
        )
    return registry


class InventoryAuthorization:
    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(inventory_catalogue_permission_registry())

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
    "INVENTORY_LOCATION_CREATE",
    "INVENTORY_LOCATION_READ",
    "INVENTORY_LOT_CREATE",
    "INVENTORY_LOT_READ",
    "INVENTORY_POOL_CREATE",
    "INVENTORY_POOL_READ",
    "INVENTORY_RESERVATION_MANAGE",
    "INVENTORY_TRANSFER_CREATE",
    "INVENTORY_WAREHOUSE_CREATE",
    "INVENTORY_WAREHOUSE_READ",
    "InventoryAuthorization",
    "inventory_catalogue_permission_registry",
    "inventory_permission_registry",
]
