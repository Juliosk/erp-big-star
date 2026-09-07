"""Pure domain model for administration and security."""

from erp.modules.admin.domain.authentication import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Session,
    UserIdentity,
)
from erp.modules.admin.domain.authorization import (
    AuthorizationDecision,
    AuthorizationPolicy,
    AuthorizationReason,
)
from erp.modules.admin.domain.corporate import Branch, Company, CorporateStatus, EconomicGroup
from erp.modules.admin.domain.exceptions import (
    AuthenticationError,
    AuthorizationError,
    DuplicatePermissionError,
    InvalidCredentialsError,
    InvalidSessionError,
    PermissionNotRegisteredError,
)
from erp.modules.admin.domain.permission import (
    DataClassification,
    Permission,
    PermissionCode,
    PermissionRegistry,
    PermissionRiskLevel,
)
from erp.modules.admin.domain.role import (
    Role,
    RoleAssignment,
    RoleAssignmentSource,
    resolve_active_permissions,
)
from erp.modules.admin.domain.scope import Scope, ScopeType, UserScope
from erp.modules.admin.domain.tax_id import Cnpj

__all__ = [
    "AuthenticatedPrincipal",
    "AuthenticationError",
    "AuthenticationLevel",
    "AuthorizationDecision",
    "AuthorizationError",
    "AuthorizationPolicy",
    "AuthorizationReason",
    "Branch",
    "Cnpj",
    "Company",
    "CorporateStatus",
    "DataClassification",
    "DuplicatePermissionError",
    "EconomicGroup",
    "InvalidCredentialsError",
    "InvalidSessionError",
    "Permission",
    "PermissionCode",
    "PermissionNotRegisteredError",
    "PermissionRegistry",
    "PermissionRiskLevel",
    "Role",
    "RoleAssignment",
    "RoleAssignmentSource",
    "Scope",
    "ScopeType",
    "Session",
    "UserIdentity",
    "UserScope",
    "resolve_active_permissions",
]
