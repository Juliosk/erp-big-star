"""Official permission vocabulary and registry owned by M1."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from erp.modules.admin.domain.authentication import AuthenticationLevel
from erp.modules.admin.domain.exceptions import (
    DuplicatePermissionError,
    PermissionNotRegisteredError,
)

_PERMISSION_PATTERN = re.compile(
    r"^(?P<domain>[a-z][a-z0-9_]*)\."
    r"(?P<resource>[a-z][a-z0-9_]*)\."
    r"(?P<action>[a-z][a-z0-9_]*)$"
)


class PermissionRiskLevel(StrEnum):
    """Risk classification required by the corporate registry."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DataClassification(StrEnum):
    """Data classifications used by field and action authorization."""

    PUBLIC_INTERNAL = "PUBLIC_INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"
    PERSONAL_DATA = "PERSONAL_DATA"


@dataclass(frozen=True, order=True, slots=True)
class PermissionCode:
    """Validated `<domain>.<resource>.<action>` permission identifier."""

    value: str

    def __post_init__(self) -> None:
        if _PERMISSION_PATTERN.fullmatch(self.value) is None:
            raise ValueError("permission must follow <domain>.<resource>.<action>")

    @property
    def domain(self) -> str:
        """Return the owning bounded-context namespace."""
        return self.value.split(".", maxsplit=1)[0]

    @property
    def resource(self) -> str:
        """Return the protected resource namespace."""
        return self.value.split(".")[1]

    @property
    def action(self) -> str:
        """Return the explicitly authorized action."""
        return self.value.rsplit(".", maxsplit=1)[1]

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Permission:
    """One registry entry with its security metadata."""

    code: PermissionCode
    description: str
    risk_level: PermissionRiskLevel
    data_classification: DataClassification
    step_up_default: AuthenticationLevel | None = None

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise ValueError("permission description must not be blank")

    @property
    def domain(self) -> str:
        """Expose the domain field required by the permission registry."""
        return self.code.domain


class PermissionRegistry:
    """In-memory domain registry that rejects ambiguity and defaults to absence."""

    def __init__(self, permissions: Iterable[Permission] = ()) -> None:
        self._permissions: dict[PermissionCode, Permission] = {}
        for permission in permissions:
            self.register(permission)

    def register(self, permission: Permission) -> None:
        """Register a unique permission code."""
        if permission.code in self._permissions:
            raise DuplicatePermissionError(str(permission.code))
        self._permissions[permission.code] = permission

    def get(self, code: PermissionCode) -> Permission:
        """Resolve an explicitly registered permission or deny by absence."""
        try:
            return self._permissions[code]
        except KeyError as error:
            raise PermissionNotRegisteredError(str(code)) from error

    def contains(self, code: PermissionCode) -> bool:
        """Return whether a code has an explicit registry entry."""
        return code in self._permissions

    def all(self) -> tuple[Permission, ...]:
        """Return the registry in deterministic permission-code order."""
        return tuple(sorted(self._permissions.values(), key=lambda item: item.code))

    def for_domain(self, domain: str) -> tuple[Permission, ...]:
        """Return only permissions owned by the requested domain."""
        return tuple(permission for permission in self.all() if permission.domain == domain)


__all__ = [
    "DataClassification",
    "Permission",
    "PermissionCode",
    "PermissionRegistry",
    "PermissionRiskLevel",
]
