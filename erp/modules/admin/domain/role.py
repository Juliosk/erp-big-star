"""Role and temporal role-assignment domain model."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from erp.modules.admin.domain.permission import PermissionCode

_ROLE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class RoleAssignmentSource(StrEnum):
    """Approved sources for a temporal role assignment."""

    MANUAL = "MANUAL"
    JOB_BASED = "JOB_BASED"
    TEMPORARY = "TEMPORARY"
    EMERGENCY = "EMERGENCY"
    DELEGATED = "DELEGATED"


@dataclass(frozen=True, slots=True)
class Role:
    """Composable digital privilege set; deliberately separate from job position."""

    role_id: UUID
    code: str
    name: str
    permission_codes: frozenset[PermissionCode]
    active: bool = True

    def __post_init__(self) -> None:
        if _ROLE_CODE_PATTERN.fullmatch(self.code) is None:
            raise ValueError("role code must use uppercase snake case")
        if not self.name.strip():
            raise ValueError("role name must not be blank")


@dataclass(frozen=True, slots=True)
class RoleAssignment:
    """Time-bounded association between a named user and a role."""

    user_id: UUID
    role_id: UUID
    valid_from: datetime
    valid_until: datetime | None
    assignment_source: RoleAssignmentSource

    def __post_init__(self) -> None:
        if self.valid_from.tzinfo is None:
            raise ValueError("role assignment timestamps must be timezone-aware")
        if self.valid_until is not None:
            if self.valid_until.tzinfo is None:
                raise ValueError("role assignment timestamps must be timezone-aware")
            if self.valid_until <= self.valid_from:
                raise ValueError("role assignment expiration must follow its start")

    def is_active_at(self, instant: datetime) -> bool:
        """Return whether the assignment is effective at the requested instant."""
        if instant.tzinfo is None:
            raise ValueError("authorization instant must be timezone-aware")
        return self.valid_from <= instant and (
            self.valid_until is None or instant < self.valid_until
        )


def resolve_active_permissions(
    *,
    user_id: UUID,
    roles: Mapping[UUID, Role],
    assignments: Iterable[RoleAssignment],
    instant: datetime,
) -> frozenset[PermissionCode]:
    """Compose permissions from active temporal assignments only."""
    granted: set[PermissionCode] = set()
    for assignment in assignments:
        if assignment.user_id != user_id or not assignment.is_active_at(instant):
            continue
        role = roles.get(assignment.role_id)
        if role is not None and role.active:
            granted.update(role.permission_codes)
    return frozenset(granted)


__all__ = ["Role", "RoleAssignment", "RoleAssignmentSource", "resolve_active_permissions"]
