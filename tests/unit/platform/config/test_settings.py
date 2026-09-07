"""Tests for typed application settings."""

import pytest
from pydantic import SecretStr

from erp.platform.config import Environment, LogLevel, Settings


def test_settings_read_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("POSTGRES_PORT", "5544")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.environment is Environment.TEST
    assert settings.debug is True
    assert settings.log_level is LogLevel.WARNING
    assert settings.postgres_port == 5544


def test_postgres_password_is_masked_in_representation() -> None:
    settings = Settings.model_validate({"postgres_password": SecretStr("must-not-appear-in-repr")})

    assert "must-not-appear-in-repr" not in repr(settings)
