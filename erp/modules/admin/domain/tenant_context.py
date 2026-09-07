"""Explicit tenant boundary propagated through M1 use cases and repositories."""

from dataclasses import dataclass
from uuid import UUID

from erp.modules.admin.domain.scope import Scope, ScopeType


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Authenticated actor and concrete hierarchy scopes for one operation.

    An empty scope collection is valid and deliberately means default-deny.
    There is no implicit global or current-company fallback.
    """

    actor_user_id: UUID
    scopes: frozenset[Scope]

    @classmethod
    def from_scopes(cls, *, actor_user_id: UUID, scopes: frozenset[Scope]) -> TenantContext:
        """Build a context after authentication and authorization resolution."""
        return cls(actor_user_id=actor_user_id, scopes=scopes)

    def ids_for(self, scope_type: ScopeType) -> frozenset[UUID]:
        """Return only identifiers granted at the requested hierarchy level."""
        return frozenset(scope.scope_id for scope in self.scopes if scope.scope_type is scope_type)

    @property
    def group_ids(self) -> frozenset[UUID]:
        return self.ids_for(ScopeType.GROUP)

    @property
    def company_ids(self) -> frozenset[UUID]:
        return self.ids_for(ScopeType.COMPANY)

    @property
    def branch_ids(self) -> frozenset[UUID]:
        return self.ids_for(ScopeType.BRANCH)


__all__ = ["TenantContext"]
