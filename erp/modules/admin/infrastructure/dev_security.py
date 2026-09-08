"""Explicit opt-in mock identity for isolated local/test environments only."""

from hmac import compare_digest
from uuid import uuid4

from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    PermissionCode,
    Scope,
    ScopeType,
)
from erp.platform.config import Settings
from erp.platform.config.settings import Environment


class DevSecurityContextResolver:
    def __init__(self, settings: Settings) -> None:
        if not settings.dev_auth_enabled or settings.environment not in {
            Environment.LOCAL,
            Environment.TEST,
        }:
            raise ValueError("Development authentication requires local/test and explicit opt-in.")
        settings = Settings.model_validate(settings.model_dump())
        assert settings.dev_auth_actor_id is not None
        self._token = settings.dev_auth_token.get_secret_value().encode("ascii")
        self._context = SecurityContext(
            principal=AuthenticatedPrincipal(
                settings.dev_auth_actor_id, uuid4(), AuthenticationLevel.LEVEL_1
            ),
            permissions=frozenset(PermissionCode(code) for code in settings.dev_auth_permissions),
            scopes=frozenset(
                Scope(ScopeType.COMPANY, company_id) for company_id in settings.dev_auth_company_ids
            ),
        )

    async def resolve(self, access_token: str) -> SecurityContext | None:
        if len(access_token) > 512 or not compare_digest(access_token.encode("utf-8"), self._token):
            return None
        return self._context


__all__ = ["DevSecurityContextResolver"]
