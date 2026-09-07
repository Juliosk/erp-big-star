"""Commands and results for authentication use cases."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from erp.modules.admin.domain import AuthenticationLevel


@dataclass(frozen=True, slots=True)
class LoginCommand:
    """Credentials accepted by the login application boundary."""

    username: str
    password: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class RefreshTokenClaims:
    """Minimal validated claims required to rotate a token pair."""

    user_id: UUID
    session_id: UUID


@dataclass(frozen=True, slots=True)
class TokenPair:
    """Opaque access and refresh tokens returned only at the API boundary."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_expires_at: datetime
    refresh_expires_at: datetime
    token_type: str = "Bearer"


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    """Successful login result without exposing stored credentials."""

    user_id: UUID
    session_id: UUID
    authentication_level: AuthenticationLevel
    tokens: TokenPair = field(repr=False)


__all__ = ["AuthenticationResult", "LoginCommand", "RefreshTokenClaims", "TokenPair"]
