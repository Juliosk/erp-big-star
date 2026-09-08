"""HTTP integration harness: identity stub is test-only, database is real."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi.testclient import TestClient

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.product.application.permissions import PRODUCT_READ
from erp.platform.config import get_settings
from tests.integration.test_product_persistence import Fixture, fixture


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "product-test-token" else None


@dataclass
class ApiFixture:
    client: TestClient
    data: Fixture
    resolver: ResolverStub

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer product-test-token"}

    @property
    def url(self) -> str:
        return f"/api/v1/products?company_id={self.data.company_id}"


@contextmanager
def product_api() -> Iterator[ApiFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = fixture()
        data = client.portal.call(manager.__aenter__)
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset({PRODUCT_READ}),
            scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
        )
        try:
            yield ApiFixture(client, data, resolver)
        finally:
            client.portal.call(manager.__aexit__, None, None, None)
