"""Unit tests for authentication application orchestration."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.application import (
    AuthenticationService,
    LoginCommand,
    RefreshTokenClaims,
    TokenPair,
)
from erp.modules.admin.domain import (
    InvalidCredentialsError,
    InvalidSessionError,
    Session,
    UserIdentity,
)

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
USER_ID = uuid4()
SESSION_ID = uuid4()


class IdentityMemoryRepository:
    def __init__(self, identity: UserIdentity | None) -> None:
        self.identity = identity
        self.last_username: str | None = None

    async def find_by_username(self, username: str) -> UserIdentity | None:
        self.last_username = username
        return self.identity


class PasswordVerifierSpy:
    def __init__(self, matches: bool = True) -> None:
        self.matches = matches
        self.dummy_verified = False

    def verify(self, password: str, password_hash: str) -> bool:
        return self.matches and password == "correct-password" and password_hash == "encoded"

    def verify_dummy(self, password: str) -> None:
        self.dummy_verified = True


class SessionMemoryRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, Session] = {}

    async def add(self, session: Session) -> None:
        self.items[session.session_id] = session

    async def get(self, session_id: UUID) -> Session | None:
        return self.items.get(session_id)

    async def save(self, session: Session) -> None:
        self.items[session.session_id] = session


class TokenServiceStub:
    def issue(self, session: Session) -> TokenPair:
        return TokenPair(
            access_token="access-token",
            refresh_token="refresh-token",
            access_expires_at=NOW + timedelta(minutes=15),
            refresh_expires_at=session.expires_at,
        )

    def decode_refresh(self, refresh_token: str) -> RefreshTokenClaims:
        if refresh_token != "refresh-token":
            raise InvalidSessionError
        return RefreshTokenClaims(user_id=USER_ID, session_id=SESSION_ID)


def build_service(
    *,
    identity: UserIdentity | None,
    password_matches: bool = True,
) -> tuple[
    AuthenticationService,
    IdentityMemoryRepository,
    PasswordVerifierSpy,
    SessionMemoryRepository,
]:
    identities = IdentityMemoryRepository(identity)
    passwords = PasswordVerifierSpy(password_matches)
    sessions = SessionMemoryRepository()
    service = AuthenticationService(
        identities=identities,
        passwords=passwords,
        sessions=sessions,
        tokens=TokenServiceStub(),
        clock=lambda: NOW,
        session_id_factory=lambda: SESSION_ID,
        session_ttl=timedelta(hours=8),
    )
    return service, identities, passwords, sessions


def test_login_creates_level_one_session_and_tokens() -> None:
    identity = UserIdentity(USER_ID, "admin@example.com", "encoded")
    service, identities, _, sessions = build_service(identity=identity)

    result = asyncio.run(service.login(LoginCommand(" Admin@Example.COM ", "correct-password")))

    assert identities.last_username == "admin@example.com"
    assert result.user_id == USER_ID
    assert result.session_id == SESSION_ID
    assert result.tokens.access_token == "access-token"
    assert sessions.items[SESSION_ID].is_active_at(NOW)


def test_login_uses_dummy_hash_for_unknown_identity() -> None:
    service, _, passwords, _ = build_service(identity=None)

    with pytest.raises(InvalidCredentialsError):
        asyncio.run(service.login(LoginCommand("missing@example.com", "wrong")))

    assert passwords.dummy_verified is True


@pytest.mark.parametrize(
    ("enabled", "password_matches"),
    [(True, False), (False, True)],
)
def test_login_does_not_disclose_invalid_password_or_disabled_identity(
    enabled: bool,
    password_matches: bool,
) -> None:
    identity = UserIdentity(USER_ID, "admin@example.com", "encoded", enabled=enabled)
    service, _, _, _ = build_service(identity=identity, password_matches=password_matches)
    supplied_password = "correct-password" if password_matches else "wrong"

    with pytest.raises(InvalidCredentialsError):
        asyncio.run(service.login(LoginCommand(identity.username, supplied_password)))


def test_refresh_and_logout_require_matching_active_session() -> None:
    identity = UserIdentity(USER_ID, "admin@example.com", "encoded")
    service, _, _, sessions = build_service(identity=identity)
    asyncio.run(service.login(LoginCommand(identity.username, "correct-password")))

    refreshed = asyncio.run(service.refresh("refresh-token"))
    asyncio.run(service.logout("refresh-token"))

    assert refreshed.access_token == "access-token"
    assert sessions.items[SESSION_ID].revoked_at == NOW
    with pytest.raises(InvalidSessionError):
        asyncio.run(service.refresh("refresh-token"))
