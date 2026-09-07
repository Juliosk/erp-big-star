"""Pure domain model for administration and security."""

from erp.modules.admin.domain.authentication import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Session,
    UserIdentity,
)
from erp.modules.admin.domain.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    InvalidSessionError,
)

__all__ = [
    "AuthenticatedPrincipal",
    "AuthenticationError",
    "AuthenticationLevel",
    "InvalidCredentialsError",
    "InvalidSessionError",
    "Session",
    "UserIdentity",
]
