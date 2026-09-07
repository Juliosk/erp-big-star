"""Authentication entities and value objects without infrastructure dependencies."""

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class AuthenticationLevel(StrEnum):
    """Authentication assurance levels defined by the security architecture."""

    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


@dataclass(frozen=True, slots=True)
class UserIdentity:
    """Authentication-facing identity owned by M1."""

    user_id: UUID
    username: str
    password_hash: str = field(repr=False)
    enabled: bool = True

    def __post_init__(self) -> None:
        normalized_username = self.username.strip().casefold()
        if not normalized_username:
            raise ValueError("username must not be blank")
        if not self.password_hash:
            raise ValueError("password_hash must not be blank")
        object.__setattr__(self, "username", normalized_username)


@dataclass(frozen=True, slots=True)
class Session:
    """Revocable authentication session with a bounded lifetime."""

    session_id: UUID
    user_id: UUID
    authentication_level: AuthenticationLevel
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("session timestamps must be timezone-aware")
        if self.expires_at <= self.created_at:
            raise ValueError("session expiration must follow creation")
        if self.revoked_at is not None and self.revoked_at.tzinfo is None:
            raise ValueError("revocation timestamp must be timezone-aware")

    def is_active_at(self, instant: datetime) -> bool:
        """Return whether the session authorizes authentication at an instant."""
        if instant.tzinfo is None:
            raise ValueError("authentication instant must be timezone-aware")
        return self.revoked_at is None and self.created_at <= instant < self.expires_at

    def revoke(self, instant: datetime) -> Session:
        """Return an idempotently revoked session snapshot."""
        if instant.tzinfo is None:
            raise ValueError("revocation instant must be timezone-aware")
        if self.revoked_at is not None:
            return self
        return replace(self, revoked_at=instant)


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Identity claims carried by a validated access token."""

    user_id: UUID
    session_id: UUID
    authentication_level: AuthenticationLevel


__all__ = ["AuthenticatedPrincipal", "AuthenticationLevel", "Session", "UserIdentity"]
