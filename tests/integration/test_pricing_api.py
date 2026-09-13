"""M9 pricing catalogue APIs use real PostgreSQL with identity resolver stubbed."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Scope,
    ScopeType,
)
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.pricing.application.permissions import (
    PRICING_MARGIN_VIEW_SENSITIVE,
    PRICING_PRICE_ACTIVATE,
    PRICING_PRICE_CREATE,
    PRICING_SIMULATE,
    PricingAuthorization,
)
from erp.modules.pricing.application.policies import (
    CreateMinimumMarginPolicy,
    PricingPolicyService,
    UpsertStandardCostSeed,
)
from erp.modules.pricing.infrastructure import (
    MinimumMarginPolicyModel,
    PostgresPricingPolicies,
    PriceListItemModel,
    PriceListModel,
    PriceListVersionModel,
    PricingSnapshotModel,
    StandardCostSeedModel,
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
                        delete(StandardCostSeedModel).where(
                            StandardCostSeedModel.company_id.in_(company_ids)
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


def test_pricing_resolve_uses_active_list_cost_policy_and_snapshot() -> None:
    with pricing_api() as api:
        assert api.resolver.context is not None
        product_id = _seed_product(api)
        price_list = api.client.post(
            "/api/v1/pricing/price-lists",
            json={
                "company_id": str(api.data.company_id),
                "code": "RESOLVE",
                "name": "Tabela Resolve",
            },
            headers=api.headers,
        ).json()
        draft = api.client.post(
            f"/api/v1/pricing/price-lists/{price_list['id']}/versions",
            json={
                "company_id": str(api.data.company_id),
                "valid_from": "2026-09-13",
                "items": [
                    {
                        "product_id": product_id,
                        "price_amount": "100.00",
                        "minimum_price_amount": "90.00",
                        "target_margin": "0.4000",
                    }
                ],
            },
            headers=api.headers,
        ).json()
        activated = api.client.post(
            f"/api/v1/pricing/price-list-versions/{draft['id']}/activate"
            f"?company_id={api.data.company_id}",
            headers={
                **api.headers,
                "If-Match": '"1"',
                "Idempotency-Key": str(uuid4()),
            },
        )
        assert activated.status_code == 200

        async def seed_policy() -> None:
            assert api.resolver.context is not None
            service = PricingPolicyService(
                PostgresPricingPolicies(api.data.database),
                PricingAuthorization(
                    CompanyAccessService(PostgresCorporateDirectory(api.data.database))
                ),
            )
            await service.upsert_standard_cost_seed(
                api.resolver.context,
                UpsertStandardCostSeed(
                    company_id=api.data.company_id,
                    product_id=UUID(product_id),
                    cost_amount=Decimal("60.00"),
                ),
            )
            await service.create_minimum_margin_policy(
                api.resolver.context,
                CreateMinimumMarginPolicy(
                    company_id=api.data.company_id,
                    code="resolve",
                    name="Resolve Margin",
                    minimum_margin=Decimal("0.3000"),
                ),
            )

        assert api.client.portal is not None
        api.client.portal.call(seed_policy)
        api.resolver.context = replace(
            api.resolver.context,
            permissions=api.resolver.context.permissions | {PRICING_MARGIN_VIEW_SENSITIVE},
        )
        response = api.client.post(
            "/api/v1/pricing/resolve",
            json={
                "company_id": str(api.data.company_id),
                "product_id": product_id,
                "quantity": "2.000000",
                "price_list_id": price_list["id"],
            },
            headers=api.headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["unit_price"] == "100.00"
        assert body["total_price"] == "200.00"
        assert body["minimum_margin"] == "0.3000"
        assert body["effective_margin"] == "0.4000"
        assert body["source"] == "PRICE_LIST:BASE"

        async def snapshot_cost_reference() -> dict[str, object] | None:
            async with api.data.database.session() as session:
                return await session.scalar(
                    select(PricingSnapshotModel.cost_reference).where(
                        PricingSnapshotModel.id == UUID(body["pricing_snapshot_id"]),
                        PricingSnapshotModel.company_id == api.data.company_id,
                    )
                )

        cost_reference = api.client.portal.call(snapshot_cost_reference)
        assert cost_reference is not None
        assert cost_reference["source"] == "LEGACY_OPENING"
        assert cost_reference["amount"] == "60.00"


def test_pricing_resolve_masks_margin_without_sensitive_permission() -> None:
    with pricing_api() as api:
        assert api.resolver.context is not None
        product_id = _seed_product(api)
        price_list = api.client.post(
            "/api/v1/pricing/price-lists",
            json={
                "company_id": str(api.data.company_id),
                "code": "MASK",
                "name": "Tabela Mask",
            },
            headers=api.headers,
        ).json()
        draft = api.client.post(
            f"/api/v1/pricing/price-lists/{price_list['id']}/versions",
            json={
                "company_id": str(api.data.company_id),
                "valid_from": "2026-09-13",
                "items": [{"product_id": product_id, "price_amount": "100.00"}],
            },
            headers=api.headers,
        ).json()
        api.client.post(
            f"/api/v1/pricing/price-list-versions/{draft['id']}/activate"
            f"?company_id={api.data.company_id}",
            headers={
                **api.headers,
                "If-Match": '"1"',
                "Idempotency-Key": str(uuid4()),
            },
        )

        async def seed_cost() -> None:
            assert api.resolver.context is not None
            service = PricingPolicyService(
                PostgresPricingPolicies(api.data.database),
                PricingAuthorization(
                    CompanyAccessService(PostgresCorporateDirectory(api.data.database))
                ),
            )
            await service.upsert_standard_cost_seed(
                api.resolver.context,
                UpsertStandardCostSeed(
                    company_id=api.data.company_id,
                    product_id=UUID(product_id),
                    cost_amount=Decimal("60.00"),
                ),
            )

        assert api.client.portal is not None
        api.client.portal.call(seed_cost)
        response = api.client.post(
            "/api/v1/pricing/resolve",
            json={
                "company_id": str(api.data.company_id),
                "product_id": product_id,
                "quantity": "1.000000",
            },
            headers=api.headers,
        )

        assert response.status_code == 200
        assert response.json()["effective_margin"] is None


def test_pricing_simulate_projects_price_without_persisting_snapshot() -> None:
    with pricing_api() as api:
        assert api.resolver.context is not None
        product_id = _seed_product(api)
        price_list = api.client.post(
            "/api/v1/pricing/price-lists",
            json={
                "company_id": str(api.data.company_id),
                "code": "SIM",
                "name": "Tabela Simulação",
            },
            headers=api.headers,
        ).json()
        draft = api.client.post(
            f"/api/v1/pricing/price-lists/{price_list['id']}/versions",
            json={
                "company_id": str(api.data.company_id),
                "valid_from": "2026-09-13",
                "items": [{"product_id": product_id, "price_amount": "120.00"}],
            },
            headers=api.headers,
        ).json()
        api.client.post(
            f"/api/v1/pricing/price-list-versions/{draft['id']}/activate"
            f"?company_id={api.data.company_id}",
            headers={
                **api.headers,
                "If-Match": '"1"',
                "Idempotency-Key": str(uuid4()),
            },
        )

        async def seed_policy_and_count_snapshots() -> int:
            assert api.resolver.context is not None
            service = PricingPolicyService(
                PostgresPricingPolicies(api.data.database),
                PricingAuthorization(
                    CompanyAccessService(PostgresCorporateDirectory(api.data.database))
                ),
            )
            await service.upsert_standard_cost_seed(
                api.resolver.context,
                UpsertStandardCostSeed(
                    company_id=api.data.company_id,
                    product_id=UUID(product_id),
                    cost_amount=Decimal("72.00"),
                ),
            )
            await service.create_minimum_margin_policy(
                api.resolver.context,
                CreateMinimumMarginPolicy(
                    company_id=api.data.company_id,
                    code="simulate",
                    name="Simulation Margin",
                    minimum_margin=Decimal("0.2500"),
                ),
            )
            async with api.data.database.session() as session:
                return int(
                    await session.scalar(
                        select(func.count()).select_from(PricingSnapshotModel)
                    )
                    or 0
                )

        assert api.client.portal is not None
        before_count = api.client.portal.call(seed_policy_and_count_snapshots)
        api.resolver.context = replace(
            api.resolver.context,
            permissions=api.resolver.context.permissions | {PRICING_MARGIN_VIEW_SENSITIVE},
        )
        response = api.client.post(
            "/api/v1/pricing/simulate",
            json={
                "company_id": str(api.data.company_id),
                "product_id": product_id,
                "quantity": "3.000000",
                "price_list_id": price_list["id"],
                "proposed_unit_price": "130.00",
            },
            headers=api.headers,
        )

        async def count_snapshots() -> int:
            async with api.data.database.session() as session:
                return int(
                    await session.scalar(
                        select(func.count()).select_from(PricingSnapshotModel)
                    )
                    or 0
                )

        assert response.status_code == 200
        body = response.json()
        assert body["persisted"] is False
        assert body["pricing_snapshot_id"] == "00000000-0000-0000-0000-000000000000"
        assert body["unit_price"] == "130.00"
        assert body["total_price"] == "390.00"
        assert body["minimum_margin"] == "0.2500"
        assert body["effective_margin"] == "0.4462"
        assert body["source"] == "SIMULATION_OVERRIDE"
        assert api.client.portal.call(count_snapshots) == before_count
