"""Official permission entries used by the M1 corporate API."""

from erp.modules.admin.domain import (
    DataClassification,
    Permission,
    PermissionCode,
    PermissionRegistry,
    PermissionRiskLevel,
)

ADMIN_ECONOMIC_GROUP_READ = PermissionCode("admin.economic_group.read")
ADMIN_COMPANY_READ = PermissionCode("admin.company.read")
ADMIN_COMPANY_CREATE = PermissionCode("admin.company.create")
ADMIN_COMPANY_UPDATE = PermissionCode("admin.company.update")
ADMIN_BRANCH_READ = PermissionCode("admin.branch.read")
ADMIN_BRANCH_CREATE = PermissionCode("admin.branch.create")
ADMIN_BRANCH_UPDATE = PermissionCode("admin.branch.update")


def corporate_permission_registry() -> PermissionRegistry:
    """Build the immutable-at-composition registry for corporate use cases."""
    entries = (
        (ADMIN_ECONOMIC_GROUP_READ, "Read authorized economic groups", PermissionRiskLevel.LOW),
        (ADMIN_COMPANY_READ, "Read authorized companies", PermissionRiskLevel.LOW),
        (ADMIN_COMPANY_CREATE, "Create a legal company", PermissionRiskLevel.HIGH),
        (ADMIN_COMPANY_UPDATE, "Update a legal company", PermissionRiskLevel.HIGH),
        (ADMIN_BRANCH_READ, "Read authorized branches", PermissionRiskLevel.LOW),
        (ADMIN_BRANCH_CREATE, "Create an operational branch", PermissionRiskLevel.HIGH),
        (ADMIN_BRANCH_UPDATE, "Update an operational branch", PermissionRiskLevel.HIGH),
    )
    return PermissionRegistry(
        Permission(
            code=code,
            description=description,
            risk_level=risk,
            data_classification=DataClassification.CONFIDENTIAL,
        )
        for code, description, risk in entries
    )


__all__ = [
    "ADMIN_BRANCH_CREATE",
    "ADMIN_BRANCH_READ",
    "ADMIN_BRANCH_UPDATE",
    "ADMIN_COMPANY_CREATE",
    "ADMIN_COMPANY_READ",
    "ADMIN_COMPANY_UPDATE",
    "ADMIN_ECONOMIC_GROUP_READ",
    "corporate_permission_registry",
]
