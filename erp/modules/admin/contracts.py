"""Explicit M1 security integration surface; no persistence types are exported."""

from erp.modules.admin.application.authorization import require_permission
from erp.modules.admin.application.company_access import CompanyAccessService
from erp.modules.admin.application.security import SecurityContext
from erp.modules.admin.domain import (
    AuthorizationPolicy,
    DataClassification,
    Permission,
    PermissionCode,
    PermissionRegistry,
    PermissionRiskLevel,
)

__all__ = [
    "AuthorizationPolicy",
    "CompanyAccessService",
    "DataClassification",
    "Permission",
    "PermissionCode",
    "PermissionRegistry",
    "PermissionRiskLevel",
    "SecurityContext",
    "require_permission",
]
