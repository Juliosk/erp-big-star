"""Application-level translation of RBAC decisions into the stable error contract."""

from erp.modules.admin.application.security import SecurityContext
from erp.modules.admin.domain import (
    AuthorizationPolicy,
    AuthorizationReason,
    PermissionCode,
    Scope,
)
from erp.platform.errors import ApplicationError


def require_permission(
    *,
    policy: AuthorizationPolicy,
    context: SecurityContext,
    permission: PermissionCode,
    scope: Scope | None = None,
) -> None:
    """Require permission and at least one explicit scope, without global fallback."""
    required_scope = scope or _first_scope(context)
    decision = policy.decide(
        principal=context.principal,
        required_permission=permission,
        granted_permissions=context.permissions,
        required_scope=required_scope,
        granted_scopes=context.scopes,
    )
    if decision.allowed:
        return
    if decision.reason is AuthorizationReason.STEP_UP_REQUIRED:
        raise ApplicationError(
            code="STEP_UP_REQUIRED",
            message="A stronger authentication level is required.",
            status_code=403,
        )
    if decision.reason in {
        AuthorizationReason.SCOPE_REQUIRED,
        AuthorizationReason.SCOPE_NOT_GRANTED,
    }:
        raise ApplicationError(
            code="SCOPE_FORBIDDEN",
            message="The requested resource is outside the authorized scope.",
            status_code=403,
        )
    raise ApplicationError(
        code="PERMISSION_FORBIDDEN",
        message="The required permission was not granted.",
        status_code=403,
    )


def _first_scope(context: SecurityContext) -> Scope | None:
    if not context.scopes:
        return None
    return min(context.scopes, key=lambda item: (item.scope_type.value, str(item.scope_id)))


__all__ = ["require_permission"]
