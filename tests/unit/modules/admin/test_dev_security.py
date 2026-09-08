"""Development identity cannot be silently enabled or moved into production."""

import asyncio
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from erp.apps.api.app import create_app
from erp.modules.admin.domain import Scope, ScopeType
from erp.modules.admin.infrastructure.dev_security import DevSecurityContextResolver
from erp.platform.config import Settings
from erp.platform.config.settings import Environment


def dev_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        dev_auth_enabled=True,
        dev_auth_token=SecretStr("test-" + uuid4().hex),
        dev_auth_actor_id=uuid4(),
        dev_auth_company_ids=(uuid4(),),
    )


def test_explicit_development_context_and_invalid_tokens() -> None:
    settings = dev_settings()
    resolver = DevSecurityContextResolver(settings)

    async def verify() -> None:
        context = await resolver.resolve(settings.dev_auth_token.get_secret_value())
        assert context is not None
        assert context.principal.user_id == settings.dev_auth_actor_id
        assert context.scopes == frozenset(
            {Scope(ScopeType.COMPANY, settings.dev_auth_company_ids[0])}
        )
        for token in ("wrong", "á", "A" * 513):
            assert await resolver.resolve(token) is None

    asyncio.run(verify())
    assert settings.dev_auth_token.get_secret_value() not in repr(settings)


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
def test_dev_auth_is_forbidden_in_non_development_environments(environment: Environment) -> None:
    values = dev_settings().model_dump()
    values["environment"] = environment
    with pytest.raises(ValidationError, match="forbidden"):
        Settings.model_validate(values)
    with pytest.raises(ValueError, match="forbidden"):
        create_app(dev_settings().model_copy(update={"environment": environment}))


def test_disabled_flag_and_incomplete_configuration_fail_closed() -> None:
    with pytest.raises(ValueError, match="opt-in"):
        DevSecurityContextResolver(Settings(dev_auth_enabled=False))
    with pytest.raises(ValidationError, match="token"):
        Settings(dev_auth_enabled=True, dev_auth_token=SecretStr(""))
    with pytest.raises(ValidationError, match="actor"):
        Settings(dev_auth_enabled=True, dev_auth_token=SecretStr("A" * 32), dev_auth_actor_id=None)
    with pytest.raises(ValueError, match="flag"):
        create_app(
            Settings(dev_auth_enabled=False),
            security_context_resolver=DevSecurityContextResolver(dev_settings()),
        )
