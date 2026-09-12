"""M5 catalogue APIs use real PostgreSQL with only the identity resolver stubbed."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    Branch,
    Scope,
    ScopeType,
)
from erp.modules.admin.infrastructure import BranchModel, BranchRepository
from erp.modules.inventory.application.permissions import (
    INVENTORY_ADJUSTMENT_CREATE,
    INVENTORY_BALANCE_READ,
    INVENTORY_LOCATION_CREATE,
    INVENTORY_LOCATION_READ,
    INVENTORY_LOT_CREATE,
    INVENTORY_LOT_READ,
    INVENTORY_POOL_CREATE,
    INVENTORY_POOL_READ,
    INVENTORY_WAREHOUSE_CREATE,
    INVENTORY_WAREHOUSE_READ,
)
from erp.modules.inventory.infrastructure import (
    InventoryBalanceModel,
    InventoryLotModel,
    InventoryPoolModel,
    InventoryPostingModel,
    InventoryReservationAllocationModel,
    InventoryReservationModel,
    InventoryTransactionModel,
    WarehouseLocationModel,
    WarehouseModel,
)
from erp.modules.product.infrastructure import ProductRepository
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.idempotency.models import IdempotencyRecordModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_product_persistence import Fixture, _cnpj, fixture

pytestmark = pytest.mark.integration


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "inventory-test-token" else None


@dataclass
class InventoryApiFixture:
    client: TestClient
    data: Fixture
    resolver: ResolverStub

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer inventory-test-token"}


@contextmanager
def inventory_api() -> Iterator[InventoryApiFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = fixture()
        data = client.portal.call(manager.__aenter__)
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset(
                {
                    INVENTORY_WAREHOUSE_READ,
                    INVENTORY_WAREHOUSE_CREATE,
                    INVENTORY_LOCATION_READ,
                    INVENTORY_LOCATION_CREATE,
                    INVENTORY_POOL_READ,
                    INVENTORY_POOL_CREATE,
                    INVENTORY_LOT_READ,
                    INVENTORY_LOT_CREATE,
                    INVENTORY_ADJUSTMENT_CREATE,
                    INVENTORY_BALANCE_READ,
                }
            ),
            scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
        )
        try:
            yield InventoryApiFixture(client, data, resolver)
        finally:

            async def cleanup_inventory() -> None:
                company_ids = (data.company_id, data.other_company_id)
                async with data.database.session() as session, session.begin():
                    await session.execute(text("SET LOCAL erp.allow_ledger_cleanup = 'on'"))
                    await session.execute(
                        delete(InventoryBalanceModel).where(
                            InventoryBalanceModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(InventoryPostingModel).where(
                            InventoryPostingModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(InventoryTransactionModel).where(
                            InventoryTransactionModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(OutboxEventModel).where(
                            OutboxEventModel.source_module == "inventory"
                        )
                    )
                    await session.execute(
                        delete(InventoryReservationAllocationModel).where(
                            InventoryReservationAllocationModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(InventoryReservationModel).where(
                            InventoryReservationModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(AuditEventModel).where(
                            AuditEventModel.module == "inventory",
                            AuditEventModel.company_id.in_(company_ids),
                        )
                    )
                    await session.execute(
                        delete(IdempotencyRecordModel).where(
                            IdempotencyRecordModel.scope.in_(
                                f"inventory:{company_id}:{data.actor_id}"
                                for company_id in company_ids
                            )
                        )
                    )
                    await session.execute(
                        delete(InventoryLotModel).where(
                            InventoryLotModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(WarehouseLocationModel).where(
                            WarehouseLocationModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(InventoryPoolModel).where(
                            InventoryPoolModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(WarehouseModel).where(WarehouseModel.company_id.in_(company_ids))
                    )
                    await session.execute(
                        delete(BranchModel).where(BranchModel.company_id.in_(company_ids))
                    )

            try:
                client.portal.call(cleanup_inventory)
            finally:
                client.portal.call(manager.__aexit__, None, None, None)


def test_inventory_catalogue_create_list_detail_and_company_isolation() -> None:
    with inventory_api() as api:

        async def seed() -> tuple[str, str]:
            branch = Branch.create(
                company_id=api.data.company_id,
                code="INV",
                name="Inventory branch",
                tax_id=_cnpj(),
                timezone="America/Sao_Paulo",
            )
            product = api.data.product(code="INVPROD")
            async with api.data.database.session() as session, session.begin():
                await BranchRepository().add(session, branch, actor_id=api.data.actor_id)
                await ProductRepository(session, company_id=api.data.company_id).add(
                    product, actor_id=api.data.actor_id
                )
            return str(branch.id), str(product.id)

        assert api.client.portal is not None
        branch_id, product_id = api.client.portal.call(seed)
        warehouse = api.client.post(
            "/api/v1/inventory/warehouses",
            json={
                "company_id": str(api.data.company_id),
                "branch_id": branch_id,
                "code": " wh-01 ",
                "name": " Principal ",
            },
            headers=api.headers,
        )
        assert warehouse.status_code == 201
        assert warehouse.headers["etag"] == '"1"'
        assert warehouse.headers["cache-control"] == "no-store"
        assert warehouse.json()["code"] == "WH-01"
        assert warehouse.json()["company_id"] == str(api.data.company_id)
        warehouse_id = warehouse.json()["id"]
        assert (
            warehouse.headers["location"]
            == f"/api/v1/inventory/warehouses/{warehouse_id}?company_id={api.data.company_id}"
        )

        location = api.client.post(
            "/api/v1/inventory/locations",
            json={
                "company_id": str(api.data.company_id),
                "warehouse_id": warehouse_id,
                "code": " a-01 ",
                "name": " Rua A ",
            },
            headers=api.headers,
        )
        assert location.status_code == 201
        assert location.json()["warehouse_id"] == warehouse_id
        pool = api.client.post(
            "/api/v1/inventory/pools",
            json={
                "company_id": str(api.data.company_id),
                "code": "mkp",
                "name": "Marketplace",
                "kind": "MARKETPLACE",
            },
            headers=api.headers,
        )
        assert pool.status_code == 201
        assert pool.json()["kind"] == "MARKETPLACE"
        lot = api.client.post(
            "/api/v1/inventory/lots",
            json={
                "company_id": str(api.data.company_id),
                "product_id": product_id,
                "code": " lote-01 ",
            },
            headers=api.headers,
        )
        assert lot.status_code == 201
        assert lot.json()["status"] == "OPEN"

        warehouses = api.client.get(
            f"/api/v1/inventory/warehouses?company_id={api.data.company_id}&page_size=1",
            headers=api.headers,
        )
        assert warehouses.status_code == 200
        assert warehouses.json()["data"][0]["id"] == warehouse_id
        assert warehouses.json()["meta"] == {"page": 1, "page_size": 1, "has_more": False}
        assert (
            api.client.get(
                f"/api/v1/inventory/warehouses/{warehouse_id}?company_id={api.data.company_id}",
                headers=api.headers,
            ).headers["etag"]
            == '"1"'
        )
        assert (
            api.client.get(
                f"/api/v1/inventory/locations?company_id={api.data.company_id}"
                f"&warehouse_id={warehouse_id}",
                headers=api.headers,
            ).json()["data"][0]["warehouse_id"]
            == warehouse_id
        )
        assert (
            api.client.get(
                f"/api/v1/inventory/pools?company_id={api.data.company_id}",
                headers=api.headers,
            ).json()["data"][0]["id"]
            == pool.json()["id"]
        )
        assert (
            api.client.get(
                f"/api/v1/inventory/lots?company_id={api.data.company_id}&status=OPEN",
                headers=api.headers,
            ).json()["data"][0]["id"]
            == lot.json()["id"]
        )
        hidden = api.client.get(
            f"/api/v1/inventory/warehouses/{warehouse_id}?company_id={api.data.other_company_id}",
            headers=api.headers,
        )
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_inventory_api_enforces_rbac_scope_and_error_contracts() -> None:
    with inventory_api() as api:
        assert api.resolver.context is not None
        original = api.resolver.context
        assert (
            api.client.get(
                f"/api/v1/inventory/warehouses?company_id={api.data.company_id}"
            ).status_code
            == 401
        )
        api.resolver.context = replace(original, permissions=frozenset())
        forbidden = api.client.get(
            f"/api/v1/inventory/warehouses?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "PERMISSION_FORBIDDEN"
        api.resolver.context = replace(original, scopes=frozenset())
        scoped = api.client.get(
            f"/api/v1/inventory/warehouses?company_id={api.data.company_id}",
            headers=api.headers,
        )
        assert scoped.status_code == 403
        assert scoped.json()["error"]["code"] == "SCOPE_FORBIDDEN"
        api.resolver.context = original
        invalid = api.client.post(
            "/api/v1/inventory/pools",
            json={
                "company_id": str(api.data.company_id),
                "code": "bad code",
                "name": "Invalid",
                "kind": "STORE",
            },
            headers=api.headers,
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "BUSINESS_VALIDATION_ERROR"
