"""Initial multi-company authorization scopes owned by M1."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class ScopeType(StrEnum):
    """Scope types approved for the first M1 implementation tranche."""

    GROUP = "GROUP"
    COMPANY = "COMPANY"
    BRANCH = "BRANCH"


@dataclass(frozen=True, slots=True)
class Scope:
    """One concrete business boundary for permission evaluation."""

    scope_type: ScopeType
    scope_id: UUID


@dataclass(frozen=True, slots=True)
class UserScope:
    """Explicit scope grant for a named user."""

    user_id: UUID
    scope: Scope


__all__ = ["Scope", "ScopeType", "UserScope"]
