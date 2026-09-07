"""Authentication orchestration isolated from HTTP, hashing, tokens, and persistence."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from erp.modules.admin.application.auth_dto import AuthenticationResult, LoginCommand, TokenPair
from erp.modules.admin.application.auth_ports import (
    IdentityRepository,
    PasswordVerifier,
    SessionRepository,
    TokenService,
)
from erp.modules.admin.domain import (
    AuthenticationLevel,
    InvalidCredentialsError,
    InvalidSessionError,
    Session,
)


class AuthenticationService:
    """Coordinate login, refresh, and logout through injected ports."""

    def __init__(
        self,
        *,
        identities: IdentityRepository,
        passwords: PasswordVerifier,
        sessions: SessionRepository,
        tokens: TokenService,
        clock: Callable[[], datetime],
        session_id_factory: Callable[[], UUID],
        session_ttl: timedelta,
    ) -> None:
        if session_ttl <= timedelta(0):
            raise ValueError("session_ttl must be positive")
        self._identities = identities
        self._passwords = passwords
        self._sessions = sessions
        self._tokens = tokens
        self._clock = clock
        self._session_id_factory = session_id_factory
        self._session_ttl = session_ttl

    async def login(self, command: LoginCommand) -> AuthenticationResult:
        """Validate credentials, create a session, and issue its token pair."""
        username = command.username.strip().casefold()
        identity = await self._identities.find_by_username(username)
        if identity is None:
            self._passwords.verify_dummy(command.password)
            raise InvalidCredentialsError

        password_matches = self._passwords.verify(command.password, identity.password_hash)
        if not password_matches or not identity.enabled:
            raise InvalidCredentialsError

        now = self._clock()
        session = Session(
            session_id=self._session_id_factory(),
            user_id=identity.user_id,
            authentication_level=AuthenticationLevel.LEVEL_1,
            created_at=now,
            expires_at=now + self._session_ttl,
        )
        await self._sessions.add(session)
        token_pair = self._tokens.issue(session)
        return AuthenticationResult(
            user_id=identity.user_id,
            session_id=session.session_id,
            authentication_level=session.authentication_level,
            tokens=token_pair,
        )

    async def refresh(self, refresh_token: str) -> TokenPair:
        """Issue a new pair only for the active session named by the refresh token."""
        claims = self._tokens.decode_refresh(refresh_token)
        session = await self._sessions.get(claims.session_id)
        if (
            session is None
            or session.user_id != claims.user_id
            or not session.is_active_at(self._clock())
        ):
            raise InvalidSessionError
        return self._tokens.issue(session)

    async def logout(self, refresh_token: str) -> None:
        """Revoke the session identified by a valid refresh token."""
        claims = self._tokens.decode_refresh(refresh_token)
        session = await self._sessions.get(claims.session_id)
        if session is None or session.user_id != claims.user_id:
            raise InvalidSessionError
        await self._sessions.save(session.revoke(self._clock()))


__all__ = ["AuthenticationService"]
