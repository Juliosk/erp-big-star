"""Default-deny permission and scope evaluation."""

from dataclasses import dataclass
from enum import StrEnum

from erp.modules.admin.domain.authentication import AuthenticatedPrincipal, AuthenticationLevel
from erp.modules.admin.domain.exceptions import PermissionNotRegisteredError
from erp.modules.admin.domain.permission import PermissionCode, PermissionRegistry
from erp.modules.admin.domain.scope import Scope

_AUTHENTICATION_RANK = {
    AuthenticationLevel.LEVEL_1: 1,
    AuthenticationLevel.LEVEL_2: 2,
    AuthenticationLevel.LEVEL_3: 3,
}


class AuthorizationReason(StrEnum):
    """Stable reasons suitable for later API and audit translation."""

    GRANTED = "GRANTED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    PERMISSION_NOT_REGISTERED = "PERMISSION_NOT_REGISTERED"
    PERMISSION_NOT_GRANTED = "PERMISSION_NOT_GRANTED"
    SCOPE_REQUIRED = "SCOPE_REQUIRED"
    SCOPE_NOT_GRANTED = "SCOPE_NOT_GRANTED"
    STEP_UP_REQUIRED = "STEP_UP_REQUIRED"


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Explicit authorization outcome; absence never means allow."""

    allowed: bool
    reason: AuthorizationReason


class AuthorizationPolicy:
    """Evaluate authentication, registry, permission, scope, and step-up in order."""

    def __init__(self, registry: PermissionRegistry) -> None:
        self._registry = registry

    def decide(
        self,
        *,
        principal: AuthenticatedPrincipal | None,
        required_permission: PermissionCode,
        granted_permissions: frozenset[PermissionCode],
        required_scope: Scope | None,
        granted_scopes: frozenset[Scope],
    ) -> AuthorizationDecision:
        """Return a default-deny authorization decision."""
        if principal is None:
            return AuthorizationDecision(False, AuthorizationReason.UNAUTHENTICATED)

        try:
            permission = self._registry.get(required_permission)
        except PermissionNotRegisteredError:
            return AuthorizationDecision(False, AuthorizationReason.PERMISSION_NOT_REGISTERED)

        if required_permission not in granted_permissions:
            return AuthorizationDecision(False, AuthorizationReason.PERMISSION_NOT_GRANTED)
        if required_scope is None:
            return AuthorizationDecision(False, AuthorizationReason.SCOPE_REQUIRED)
        if required_scope not in granted_scopes:
            return AuthorizationDecision(False, AuthorizationReason.SCOPE_NOT_GRANTED)
        if (
            permission.step_up_default is not None
            and _AUTHENTICATION_RANK[principal.authentication_level]
            < _AUTHENTICATION_RANK[permission.step_up_default]
        ):
            return AuthorizationDecision(False, AuthorizationReason.STEP_UP_REQUIRED)
        return AuthorizationDecision(True, AuthorizationReason.GRANTED)


__all__ = ["AuthorizationDecision", "AuthorizationPolicy", "AuthorizationReason"]
