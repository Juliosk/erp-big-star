"""Unit tests for the pure authentication domain model."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from erp.modules.admin.domain import AuthenticationLevel, Session, UserIdentity

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
NAIVE_NOW = NOW.replace(tzinfo=None)


def test_identity_normalizes_username_and_hides_password_hash() -> None:
    identity = UserIdentity(
        user_id=uuid4(),
        username="  Admin@Example.COM ",
        password_hash="encoded-secret",
    )

    assert identity.username == "admin@example.com"
    assert "encoded-secret" not in repr(identity)


def test_session_can_be_revoked_idempotently() -> None:
    now = NOW
    session = Session(
        session_id=uuid4(),
        user_id=uuid4(),
        authentication_level=AuthenticationLevel.LEVEL_1,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )

    assert session.is_active_at(now)
    revoked = session.revoke(now + timedelta(minutes=1))
    assert not revoked.is_active_at(now + timedelta(minutes=2))
    assert revoked.revoke(now + timedelta(minutes=3)) is revoked


@pytest.mark.parametrize(
    ("created_at", "expires_at", "message"),
    [
        (NAIVE_NOW, NAIVE_NOW + timedelta(hours=1), "timestamps must be timezone-aware"),
        (
            datetime(2026, 9, 7, 13, tzinfo=UTC),
            datetime(2026, 9, 7, 12, tzinfo=UTC),
            "expiration must follow creation",
        ),
    ],
)
def test_session_rejects_invalid_time_boundaries(
    created_at: datetime,
    expires_at: datetime,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        Session(
            session_id=uuid4(),
            user_id=uuid4(),
            authentication_level=AuthenticationLevel.LEVEL_1,
            created_at=created_at,
            expires_at=expires_at,
        )
