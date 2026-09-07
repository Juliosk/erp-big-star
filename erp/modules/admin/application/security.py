"""Technology-neutral security context resolved from validated access tokens."""

from dataclasses import dataclass
from typing import Protocol

from erp.modules.admin.domain import AuthenticatedPrincipal, PermissionCode, Scope, TenantContext


@dataclass(frozen=True, slots=True)
class SecurityContext:
    """Authenticated principal with its current permission and scope grants."""

    principal: AuthenticatedPrincipal
    permissions: frozenset[PermissionCode]
    scopes: frozenset[Scope]

    def tenant_context(self) -> TenantContext:
        """Propagate the named actor and exact scopes into tenant-aware persistence."""
        return TenantContext.from_scopes(
            actor_user_id=self.principal.user_id,
            scopes=self.scopes,
        )


class SecurityContextResolver(Protocol):
    """Validate an access token and resolve fresh authorization grants."""

    async def resolve(self, access_token: str) -> SecurityContext | None:
        """Return no context when the token is invalid, expired or revoked."""
        ...


__all__ = ["SecurityContext", "SecurityContextResolver"]
