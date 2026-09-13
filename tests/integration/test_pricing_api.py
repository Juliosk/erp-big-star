"""M9 pricing catalogue APIs use real PostgreSQL with identity resolver stubbed."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

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
from erp.modules.pricing.infrastructure.pricing_effects import PRICE_LIST_VERSION_ACTIVATED
from erp.modules.product.infrastructure import ProductRepository
from erp.platform.audit import AuditEventModel
from erp.platform.idempotency import IdempotencyRecordModel
from erp.platform.outbox import OutboxEventModel
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
                        delete(IdempotencyRecordModel).where(
                            IdempotencyRecordModel.scope.like("pricing:%")
                        )
                    )
                    await session.execute(
                        delete(OutboxEventModel).where(
                            OutboxEventModel.source_module == "pricing"
                        )
                    )
                    await session.execute(
                        delete(AuditEventModel).where(AuditEventModel.module == "pricing")
                    )
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


def test_pricing_api_activates_version_with_etag_audit_outbox_and_idempotency() -> None:
    with pricing_api() as api:
        product_id = _seed_product(api)
        price_list = api.client.post(
            "/api/v1/pricing/price-lists",
            json={
                "company_id": str(api.data.company_id),
                "code": "ATIVACAO",
                "name": "Tabela Ativação",
            },
            headers=api.headers,
        ).json()
        draft = api.client.post(
            f"/api/v1/pricing/price-lists/{price_list['id']}/versions",
            json={
                "company_id": str(api.data.company_id),
                "valid_from": "2026-09-13",
                "items": [{"product_id": product_id, "price_amount": "39.90"}],
            },
            headers=api.headers,
        ).json()
        idempotency_key = str(uuid4())
        first = api.client.post(
            f"/api/v1/pricing/price-list-versions/{draft['id']}/activate"
            f"?company_id={api.data.company_id}",
            headers={
                **api.headers,
                "If-Match": '"1"',
                "Idempotency-Key": idempotency_key,
            },
        )
        replay = api.client.post(
            f"/api/v1/pricing/price-list-versions/{draft['id']}/activate"
            f"?company_id={api.data.company_id}",
            headers={
                **api.headers,
                "If-Match": '"1"',
                "Idempotency-Key": idempotency_key,
            },
        )
        stale = api.client.post(
            f"/api/v1/pricing/price-list-versions/{draft['id']}/activate"
            f"?company_id={api.data.company_id}",
            headers={
                **api.headers,
                "If-Match": '"1"',
                "Idempotency-Key": str(uuid4()),
            },
        )
        detail = api.client.get(
            f"/api/v1/pricing/price-list-versions/{draft['id']}"
            f"?company_id={api.data.company_id}",
            headers=api.headers,
        )

        assert first.status_code == 200
        assert first.headers["etag"] == '"2"'
        assert first.headers["idempotency-replayed"] == "false"
        assert first.json()["price_list_version"]["status"] == "ACTIVE"
        assert first.json()["event_id"] is not None
        assert first.json()["audit_event_id"] is not None
        assert replay.status_code == 200
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.json()["price_list_version"] == first.json()["price_list_version"]
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"2"'
        assert detail.json()["status"] == "ACTIVE"

        async def count_effects() -> tuple[int, int]:
            async with api.data.database.session() as session:
                outbox_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(
                        OutboxEventModel.source_module == "pricing",
                        OutboxEventModel.event_type == PRICE_LIST_VERSION_ACTIVATED,
                        OutboxEventModel.aggregate_id == UUID(draft["id"]),
                    )
                )
                audit_count = await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(
                        AuditEventModel.module == "pricing",
                        AuditEventModel.operation == PRICE_LIST_VERSION_ACTIVATED,
                        AuditEventModel.entity_id == UUID(draft["id"]),
                    )
                )
                return int(outbox_count or 0), int(audit_count or 0)

        assert api.client.portal is not None
        assert api.client.portal.call(count_effects) == (1, 1)


def test_pricing_api_requires_if_match_for_activation() -> None:
    with pricing_api() as api:
        response = api.client.post(
            f"/api/v1/pricing/price-list-versions/{uuid4()}/activate"
            f"?company_id={api.data.company_id}",
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )

        assert response.status_code == 428
        assert response.json()["error"]["code"] == "PRECONDITION_REQUIRED"
