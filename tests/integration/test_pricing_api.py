"""M9 pricing catalogue APIs use real PostgreSQL with identity resolver stubbed."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Scope,
    ScopeType,
)
from erp.modules.pricing.application.permissions import (
    PRICING_PRICE_ACTIVATE,
    PRICING_PRICE_CREATE,
    PRICING_SIMULATE,
)
from erp.modules.pricing.infrastructure import (
    MinimumMarginPolicyModel,
    PriceListItemModel,
    PriceListModel,
    PriceListVersionModel,
    PricingSnapshotModel,
)
from erp.modules.product.infrastructure import ProductRepository
from tests.integration.test_product_persistence import Fixture, fixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "pricing-test-token" else None


@dataclass
class PricingApiFixture:
    client: TestClient
    data: Fixture
    resolver: ResolverStub

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer pricing-test-token"}


@contextmanager
def pricing_api() -> Iterator[PricingApiFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = fixture()
        data = client.portal.call(manager.__aenter__)
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset(
                {PRICING_SIMULATE, PRICING_PRICE_CREATE, PRICING_PRICE_ACTIVATE}
            ),
            scopes=frozenset(
                {
                    Scope(ScopeType.COMPANY, data.company_id),
                    Scope(ScopeType.COMPANY, data.other_company_id),
                }
            ),
        )
        try:
            yield PricingApiFixture(client, data, resolver)
        finally:

            async def cleanup_pricing() -> None:
                company_ids = (data.company_id, data.other_company_id)
                async with data.database.session() as session, session.begin():
                    await session.execute(
                        delete(PricingSnapshotModel).where(
                            PricingSnapshotModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(MinimumMarginPolicyModel).where(
                            MinimumMarginPolicyModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(PriceListItemModel).where(
                            PriceListItemModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(PriceListVersionModel).where(
                            PriceListVersionModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(PriceListModel).where(PriceListModel.company_id.in_(company_ids))
                    )

            try:
                client.portal.call(cleanup_pricing)
            finally:
                client.portal.call(manager.__aexit__, None, None, None)


def _seed_product(api: PricingApiFixture) -> str:
    async def seed() -> str:
        product = api.data.product(code="PRICE")
        async with api.data.database.session() as session, session.begin():
            await ProductRepository(session, company_id=api.data.company_id).add(
                product, actor_id=api.data.actor_id
            )
        return str(product.id)

    assert api.client.portal is not None
    return str(api.client.portal.call(seed))


def test_pricing_api_creates_lists_versions_items_and_reads_company_scope() -> None:
    with pricing_api() as api:
        product_id = _seed_product(api)
        created = api.client.post(
            "/api/v1/pricing/price-lists",
            json={
                "company_id": str(api.data.company_id),
                "code": "varejo",
                "name": "Tabela Varejo",
                "price_type": "BASE",
            },
            headers=api.headers,
        )
        assert created.status_code == 201
        assert created.headers["etag"] == '"1"'
        price_list = created.json()
        assert price_list["code"] == "VAREJO"
        assert price_list["company_id"] == str(api.data.company_id)

        version = api.client.post(
            f"/api/v1/pricing/price-lists/{price_list['id']}/versions",
            json={
                "company_id": str(api.data.company_id),
                "valid_from": "2026-09-13",
                "source": "legacy_opening",
                "items": [
                    {
                        "product_id": product_id,
                        "price_amount": "29.90",
                        "minimum_price_amount": "24.50",
                        "target_margin": "0.3200",
                    }
                ],
            },
            headers=api.headers,
        )
        assert version.status_code == 201
        assert version.headers["etag"] == '"1"'
        assert version.json()["items"][0]["price"] == "29.90"
        assert version.json()["source"] == "LEGACY_OPENING"

        lists = api.client.get(
            f"/api/v1/pricing/price-lists?company_id={api.data.company_id}",
            headers=api.headers,
        )
        foreign = api.client.get(
            f"/api/v1/pricing/price-lists?company_id={api.data.other_company_id}",
            headers=api.headers,
        )
        versions = api.client.get(
            f"/api/v1/pricing/price-lists/{price_list['id']}/versions"
            f"?company_id={api.data.company_id}",
            headers=api.headers,
        )
        detail = api.client.get(
            f"/api/v1/pricing/price-list-versions/{version.json()['id']}"
            f"?company_id={api.data.company_id}",
            headers=api.headers,
        )

        assert lists.status_code == foreign.status_code == versions.status_code == 200
        assert len(lists.json()["data"]) == 1
        assert foreign.json()["data"] == []
        assert versions.json()["data"][0]["items"][0]["minimum_price"] == "24.50"
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"1"'


def test_pricing_api_enforces_rbac_scope_and_error_contract() -> None:
    with pricing_api() as api:
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            permissions=frozenset({PRICING_SIMULATE}),
        )
        forbidden = api.client.post(
            "/api/v1/pricing/price-lists",
            json={
                "company_id": str(api.data.company_id),
                "code": "SEM-PERMISSAO",
                "name": "Sem permissão",
            },
            headers=api.headers,
        )
        missing = api.client.get(
            f"/api/v1/pricing/price-lists/{uuid4()}?company_id={api.data.company_id}",
            headers=api.headers,
        )

        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "PERMISSION_FORBIDDEN"
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
