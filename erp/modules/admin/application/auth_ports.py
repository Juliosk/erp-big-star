"""Ports required by authentication application services."""

from typing import Protocol
from uuid import UUID

from erp.modules.admin.application.auth_dto import RefreshTokenClaims, TokenPair
from erp.modules.admin.domain import Session, UserIdentity


class IdentityRepository(Protocol):
    """Load authentication identities without leaking persistence details."""

    async def find_by_username(self, username: str) -> UserIdentity | None: ...


class PasswordVerifier(Protocol):
    """Verify password hashes and equalize unknown-user timing."""

    def verify(self, password: str, password_hash: str) -> bool: ...

    def verify_dummy(self, password: str) -> None: ...


class SessionRepository(Protocol):
    """Persist and retrieve revocable sessions."""

    async def add(self, session: Session) -> None: ...

    async def get(self, session_id: UUID) -> Session | None: ...

    async def save(self, session: Session) -> None: ...


class TokenService(Protocol):
    """Issue opaque token pairs and validate refresh tokens."""

    def issue(self, session: Session) -> TokenPair: ...

    def decode_refresh(self, refresh_token: str) -> RefreshTokenClaims: ...


__all__ = ["IdentityRepository", "PasswordVerifier", "SessionRepository", "TokenService"]
