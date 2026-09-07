"""Pure domain model for administration and security."""

from erp.modules.admin.domain.authentication import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Session,
    UserIdentity,
)
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

__all__ = [
    "AuthenticatedPrincipal",
    "AuthenticationError",
    "AuthenticationLevel",
    "AuthorizationError",
    "DataClassification",
    "DuplicatePermissionError",
    "InvalidCredentialsError",
    "InvalidSessionError",
    "Permission",
    "PermissionCode",
    "PermissionNotRegisteredError",
    "PermissionRegistry",
    "PermissionRiskLevel",
    "Session",
    "UserIdentity",
]
