"""Tests for the SQLAlchemy database adapter."""

import asyncio

from sqlalchemy.engine import URL

from erp.platform.config import Settings
from erp.platform.database import Database


def test_database_url_preserves_special_password_characters() -> None:
    settings = Settings.model_validate(
        {
            "postgres_host": "database.internal",
            "postgres_port": 5544,
            "postgres_db": "erp_test",
            "postgres_user": "erp_user",
            "postgres_password": "p@ss:/word",
        }
    )

    url = Database.build_url(settings)

    assert isinstance(url, URL)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "database.internal"
    assert url.port == 5544
    assert url.database == "erp_test"
    assert url.username == "erp_user"
    assert url.password == "p@ss:/word"
    assert "p@ss:/word" not in url.render_as_string(hide_password=True)


def test_database_uses_expected_async_engine() -> None:
    settings = Settings.model_validate({"postgres_password": "local-test-only"})
    database = Database(settings)

    assert database.engine.url.drivername == "postgresql+asyncpg"

    asyncio.run(database.dispose())
