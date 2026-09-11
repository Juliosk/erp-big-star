"""Inventory adjustment API: ledger, balance, Audit, Outbox and idempotency."""

from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from erp.modules.admin.domain import Branch
from erp.modules.admin.infrastructure import BranchRepository
from erp.modules.inventory.application.permissions import (
    INVENTORY_ADJUSTMENT_CREATE,
    INVENTORY_WAREHOUSE_CREATE,
    INVENTORY_WAREHOUSE_READ,
)
from erp.modules.inventory.infrastructure import (
    InventoryBalanceModel,
    InventoryPostingModel,
    InventoryTransactionModel,
)
from erp.modules.product.infrastructure import ProductRepository
from erp.platform.audit import AuditEventModel
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_inventory_api import InventoryApiFixture, inventory_api
from tests.integration.test_product_persistence import _cnpj

pytestmark = pytest.mark.integration


def _allow_adjustment(api: InventoryApiFixture) -> None:
    assert api.resolver.context is not None
    api.resolver.context = replace(
        api.resolver.context,
        permissions=frozenset(
            {
                INVENTORY_ADJUSTMENT_CREATE,
                INVENTORY_WAREHOUSE_CREATE,
                INVENTORY_WAREHOUSE_READ,
            }
        ),
    )


def _seed_stock_dimensions(api: InventoryApiFixture) -> tuple[str, str]:
    async def seed() -> tuple[str, str]:
        branch = Branch.create(
            company_id=api.data.company_id,
            code="ADJ",
            name="Adjustment branch",
            tax_id=_cnpj(),
            timezone="America/Sao_Paulo",
        )
        product = api.data.product(code="ADJPROD")
        async with api.data.database.session() as session, session.begin():
            await BranchRepository().add(session, branch, actor_id=api.data.actor_id)
            await ProductRepository(session, company_id=api.data.company_id).add(
                product, actor_id=api.data.actor_id
            )
        warehouse = api.client.post(
            "/api/v1/inventory/warehouses",
            json={
                "company_id": str(api.data.company_id),
                "branch_id": str(branch.id),
                "code": "WHADJ",
                "name": "Adjustment warehouse",
            },
            headers=api.headers,
        )
        assert warehouse.status_code == 201
        return str(product.id), warehouse.json()["id"]

    assert api.client.portal is not None
    return cast("tuple[str, str]", api.client.portal.call(seed))


def _adjustment_body(
    api: InventoryApiFixture, *, product_id: str, warehouse_id: str, quantity: str = "5"
) -> dict[str, Any]:
    return {
        "company_id": str(api.data.company_id),
        "adjustment_type": "INBOUND",
        "reason": "Initial inventory count",
        "lines": [
            {
                "product_id": product_id,
                "warehouse_id": warehouse_id,
                "state": "AVAILABLE",
                "quantity": quantity,
            }
        ],
    }


def test_inventory_adjustment_creates_ledger_balance_audit_outbox_and_replays() -> None:
    with inventory_api() as api:
        _allow_adjustment(api)
        product_id, warehouse_id = _seed_stock_dimensions(api)
        correlation_id, request_id, idempotency_key = uuid4(), uuid4(), uuid4()
        headers = {
            **api.headers,
            "Idempotency-Key": str(idempotency_key),
            "X-Correlation-ID": str(correlation_id),
            "X-Request-ID": str(request_id),
        }
        first = api.client.post(
            "/api/v1/inventory/adjustments",
            json=_adjustment_body(api, product_id=product_id, warehouse_id=warehouse_id),
            headers=headers,
        )
        replay = api.client.post(
            "/api/v1/inventory/adjustments",
            json=_adjustment_body(api, product_id=product_id, warehouse_id=warehouse_id),
            headers=headers,
        )
        assert first.status_code == replay.status_code == 201
        assert first.headers["idempotency-replayed"] == "false"
        assert replay.headers["idempotency-replayed"] == "true"
        assert first.json()["transaction_id"] == replay.json()["transaction_id"]
        assert first.json()["balances"][0]["quantity"] == "5.000000"
        assert first.json()["balances"][0]["version"] == 1

        async def verify() -> None:
            async with api.data.database.session() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(InventoryTransactionModel)
                        .where(InventoryTransactionModel.company_id == api.data.company_id)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(InventoryPostingModel)
                        .where(InventoryPostingModel.company_id == api.data.company_id)
                    )
                    == 1
                )
                balance = await session.scalar(
                    select(InventoryBalanceModel).where(
                        InventoryBalanceModel.company_id == api.data.company_id
                    )
                )
                audit = await session.get(AuditEventModel, UUID(first.json()["audit_event_id"]))
                outbox = await session.scalar(
                    select(OutboxEventModel).where(
                        OutboxEventModel.event_id == UUID(first.json()["event_id"])
                    )
                )
                assert balance is not None
                assert audit is not None
                assert outbox is not None
                envelope = MessageEnvelope.model_validate(outbox.payload)
                assert envelope.message_type == "InventoryAdjusted"
                assert envelope.aggregate_type == "inventory_adjustment"
                assert envelope.company_id == api.data.company_id
                assert envelope.correlation_id == audit.correlation_id == correlation_id
                assert envelope.request_id == audit.request_id == request_id
                assert audit.module == "inventory"
                assert audit.operation == "InventoryAdjusted"
                assert audit.entity_id == UUID(first.json()["transaction_id"])

        assert api.client.portal is not None
        api.client.portal.call(verify)


def test_negative_adjustment_rolls_back_ledger_balance_audit_and_outbox() -> None:
    with inventory_api() as api:
        _allow_adjustment(api)
        product_id, warehouse_id = _seed_stock_dimensions(api)
        body = _adjustment_body(api, product_id=product_id, warehouse_id=warehouse_id)
        body["adjustment_type"] = "OUTBOUND"
        failed = api.client.post(
            "/api/v1/inventory/adjustments",
            json=body,
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
        )
        assert failed.status_code == 409
        assert failed.json()["error"]["code"] == "INVENTORY_NEGATIVE_BALANCE"

        async def counts() -> tuple[int, int, int, int]:
            async with api.data.database.session() as session:
                transactions = await session.scalar(
                    select(func.count())
                    .select_from(InventoryTransactionModel)
                    .where(InventoryTransactionModel.company_id == api.data.company_id)
                )
                balances = await session.scalar(
                    select(func.count())
                    .select_from(InventoryBalanceModel)
                    .where(InventoryBalanceModel.company_id == api.data.company_id)
                )
                audit = await session.scalar(
                    select(func.count())
                    .select_from(AuditEventModel)
                    .where(
                        AuditEventModel.module == "inventory",
                        AuditEventModel.company_id == api.data.company_id,
                    )
                )
                outbox = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(OutboxEventModel.source_module == "inventory")
                )
                return transactions or 0, balances or 0, audit or 0, outbox or 0

        assert api.client.portal is not None
        assert api.client.portal.call(counts) == (0, 0, 0, 0)
