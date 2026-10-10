"""M6 goods receipt API and M17/M5 orchestration against PostgreSQL."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text

from erp.modules.admin.domain import Branch
from erp.modules.admin.infrastructure import BranchModel, BranchRepository
from erp.modules.inventory.domain import Warehouse
from erp.modules.inventory.infrastructure import WarehouseModel, WarehouseRepository
from erp.modules.inventory.infrastructure.balance_model import InventoryBalanceModel
from erp.modules.inventory.infrastructure.ledger_model import (
    InventoryPostingModel,
    InventoryTransactionModel,
)
from erp.modules.procurement.application import (
    PROCUREMENT_RECEIPT_MANAGE,
    PROCUREMENT_RECEIPT_READ,
)
from erp.modules.procurement.infrastructure import (
    GOODS_RECEIPT_LIFECYCLE_CONSUMER,
    GoodsReceiptLifecycleConsumer,
    GoodsReceiptModel,
    ReceiptItemModel,
)
from erp.platform.idempotency import IdempotencyRecordModel
from erp.platform.inbox import InboxEventModel
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_procurement_purchasing_api import (
    PurchasingApiFixture,
    action,
    approve_requisition,
    create_order,
    create_supplier,
    purchasing_api,
)
from tests.integration.test_procurement_supplier_repository import _cnpj

pytestmark = pytest.mark.integration


@contextmanager
def goods_receipt_api() -> Iterator[tuple[PurchasingApiFixture, Warehouse]]:
    with purchasing_api() as api:
        portal = api.client.portal
        assert portal is not None
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            permissions=api.resolver.context.permissions
            | {PROCUREMENT_RECEIPT_READ, PROCUREMENT_RECEIPT_MANAGE},
        )
        branch = Branch.create(
            company_id=api.data.company_id,
            code=f"BR{uuid4().hex[:10]}",
            name="Filial recebimento",
            tax_id=_cnpj(),
            timezone="America/Sao_Paulo",
        )
        warehouse = Warehouse.create(
            company_id=api.data.company_id,
            branch_id=branch.id,
            code=f"WH{uuid4().hex[:10]}",
            name="Deposito recebimento",
        )

        async def setup() -> None:
            async with api.data.database.session() as session, session.begin():
                await BranchRepository().add(session, branch, actor_id=api.data.actor_id)
                await WarehouseRepository(session, company_id=api.data.company_id).add(
                    warehouse, actor_id=api.data.actor_id
                )

        portal.call(setup)
        try:
            yield api, warehouse
        finally:

            async def cleanup() -> None:
                async with api.data.database.session() as session, session.begin():
                    await session.execute(
                        delete(InboxEventModel).where(
                            InboxEventModel.consumer_name == GOODS_RECEIPT_LIFECYCLE_CONSUMER
                        )
                    )
                    await session.execute(
                        delete(OutboxEventModel).where(
                            OutboxEventModel.aggregate_type == "goods_receipt",
                            OutboxEventModel.payload["company_id"].astext
                            == str(api.data.company_id),
                        )
                    )
                    await session.execute(text("SET LOCAL erp.allow_ledger_cleanup = 'on'"))
                    await session.execute(
                        delete(InventoryBalanceModel).where(
                            InventoryBalanceModel.company_id == api.data.company_id
                        )
                    )
                    await session.execute(
                        delete(InventoryPostingModel).where(
                            InventoryPostingModel.company_id == api.data.company_id
                        )
                    )
                    await session.execute(
                        delete(InventoryTransactionModel).where(
                            InventoryTransactionModel.company_id == api.data.company_id
                        )
                    )
                    await session.execute(
                        delete(ReceiptItemModel).where(
                            ReceiptItemModel.company_id == api.data.company_id
                        )
                    )
                    await session.execute(
                        delete(GoodsReceiptModel).where(
                            GoodsReceiptModel.company_id == api.data.company_id
                        )
                    )
                    await session.execute(
                        delete(IdempotencyRecordModel).where(
                            IdempotencyRecordModel.scope.like(
                                f"procurement-receipt:{api.data.company_id}:%"
                            )
                        )
                    )
                    await session.execute(
                        delete(WarehouseModel).where(WarehouseModel.id == warehouse.id)
                    )
                    await session.execute(delete(BranchModel).where(BranchModel.id == branch.id))

            portal.call(cleanup)


def _issued_order(api: PurchasingApiFixture) -> Any:
    requisition = approve_requisition(api)
    supplier = create_supplier(api)
    created = create_order(api, requisition, supplier)
    submitted = action(
        api, "purchase-orders", created.json()["id"], "submit", created.headers["etag"]
    )
    approved = action(
        api, "purchase-orders", created.json()["id"], "approve", submitted.headers["etag"]
    )
    issued = action(api, "purchase-orders", created.json()["id"], "issue", approved.headers["etag"])
    assert issued.status_code == 200
    return issued


def _create_receipt(
    api: PurchasingApiFixture, warehouse: Warehouse, issued: Any, *, key: str | None = None
) -> Any:
    return api.client.post(
        "/api/v1/procurement/goods-receipts",
        headers={**api.headers, "Idempotency-Key": key or str(uuid4())},
        json={
            "company_id": str(api.data.company_id),
            "number": f"GR-{uuid4().hex[:10]}",
            "purchase_order_id": issued.json()["id"],
            "warehouse_id": str(warehouse.id),
            "tolerance_percentage": "5",
            "items": [
                {
                    "purchase_order_item_id": issued.json()["items"][0]["id"],
                    "received_quantity": "10",
                    "specification_conforms": True,
                }
            ],
        },
    )


def _mutate(api: PurchasingApiFixture, receipt: Any, action_name: str, body: Any) -> Any:
    return api.client.post(
        f"/api/v1/procurement/goods-receipts/{receipt.json()['id']}/{action_name}"
        f"?company_id={api.data.company_id}",
        headers={
            **api.headers,
            "If-Match": receipt.headers["etag"],
            "Idempotency-Key": str(uuid4()),
        },
        json=body,
    )


def test_complete_goods_receipt_m17_m5_flow_and_filters() -> None:
    with goods_receipt_api() as (api, warehouse):
        issued = _issued_order(api)
        created = _create_receipt(api, warehouse, issued)
        assert created.status_code == 201
        assert created.headers["etag"] == '"1"'
        assert created.json()["status"] == "DRAFT"

        received = _mutate(api, created, "receive", {})
        assert received.status_code == 200
        assert received.json()["status"] == "RECEIVED"
        item = received.json()["items"][0]
        inspected = _mutate(
            api,
            received,
            "inspect",
            {
                "decisions": [
                    {
                        "receipt_item_id": item["id"],
                        "inspection_id": str(uuid4()),
                        "disposition": "PARTIAL_ACCEPTANCE",
                        "approved_quantity": "7",
                        "quarantine_quantity": "3",
                        "reason_code": "QUALITY-HOLD",
                    }
                ]
            },
        )
        assert inspected.status_code == 200
        assert [posting["state"] for posting in inspected.json()["posting_requests"]] == [
            "AVAILABLE",
            "QUARANTINE",
        ]
        blocked = _mutate(api, inspected, "post-to-inventory", None)
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "FISCAL_RECONCILIATION_REQUIRED"

        listing = api.client.get(
            "/api/v1/procurement/goods-receipts",
            headers=api.headers,
            params={
                "company_id": str(api.data.company_id),
                "purchase_order_id": issued.json()["id"],
                "supplier_id": issued.json()["supplier_id"],
                "status": "INSPECTED",
            },
        )
        assert listing.status_code == 200
        assert [value["id"] for value in listing.json()["data"]] == [inspected.json()["id"]]

        async def balances() -> list[tuple[str, str]]:
            async with api.data.database.session() as session:
                values = await session.scalars(
                    select(InventoryBalanceModel).where(
                        InventoryBalanceModel.company_id == api.data.company_id,
                        InventoryBalanceModel.product_id == UUID(item["product_id"]),
                    )
                )
                return sorted((value.state, str(value.quantity)) for value in values)

        portal = api.client.portal
        assert portal is not None
        assert portal.call(balances) == []


def test_receipt_idempotency_etag_rbac_and_tenant_scope() -> None:
    with goods_receipt_api() as (api, warehouse):
        issued = _issued_order(api)
        key = str(uuid4())
        created = _create_receipt(api, warehouse, issued, key=key)
        assert created.status_code == 201
        replay_body = created.request.content
        replay = api.client.post(
            "/api/v1/procurement/goods-receipts",
            headers={
                **api.headers,
                "Idempotency-Key": key,
                "Content-Type": "application/json",
            },
            content=replay_body,
        )
        assert replay.status_code == 201
        assert replay.json()["id"] == created.json()["id"]

        missing_match = api.client.post(
            f"/api/v1/procurement/goods-receipts/{created.json()['id']}/receive"
            f"?company_id={api.data.company_id}",
            headers={**api.headers, "Idempotency-Key": str(uuid4())},
            json={},
        )
        assert missing_match.status_code == 428
        assert missing_match.json()["error"]["code"] == "PRECONDITION_REQUIRED"

        foreign = api.client.get(
            f"/api/v1/procurement/goods-receipts/{created.json()['id']}"
            f"?company_id={api.data.other_company_id}",
            headers=api.headers,
        )
        assert foreign.status_code == 404
        assert foreign.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            permissions=api.resolver.context.permissions - {PROCUREMENT_RECEIPT_MANAGE},
        )
        denied = _create_receipt(api, warehouse, issued)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PERMISSION_FORBIDDEN"


def test_receipt_events_are_transactional_and_consumed_exactly_once() -> None:
    with goods_receipt_api() as (api, warehouse):
        issued = _issued_order(api)
        created = _create_receipt(api, warehouse, issued)
        received = _mutate(api, created, "receive", {})
        item = received.json()["items"][0]
        inspected = _mutate(
            api,
            received,
            "inspect",
            {
                "decisions": [
                    {
                        "receipt_item_id": item["id"],
                        "inspection_id": str(uuid4()),
                        "disposition": "APPROVE",
                        "approved_quantity": item["received_quantity"],
                    }
                ]
            },
        )
        blocked = _mutate(api, inspected, "post-to-inventory", None)
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "FISCAL_RECONCILIATION_REQUIRED"

        async def verify() -> tuple[list[str], list[tuple[bool, bool]]]:
            async with api.data.database.session() as session:
                models = list(
                    await session.scalars(
                        select(OutboxEventModel)
                        .where(OutboxEventModel.aggregate_id == UUID(inspected.json()["id"]))
                        .order_by(OutboxEventModel.occurred_at)
                    )
                )
            consumer = GoodsReceiptLifecycleConsumer(api.data.database)
            envelopes = [MessageEnvelope.model_validate(value.payload) for value in models]
            outcomes = []
            for envelope in envelopes:
                first = await consumer.consume(envelope)
                replay = await consumer.consume(envelope)
                outcomes.extend(
                    [(first.processed, first.duplicate), (replay.processed, replay.duplicate)]
                )
            return [value.event_type for value in models], outcomes

        portal = api.client.portal
        assert portal is not None
        event_types, outcomes = portal.call(verify)
        assert event_types == [
            "GoodsReceiptCreated",
            "GoodsReceiptReceived",
            "GoodsReceiptInspected",
        ]
        assert outcomes == [(True, False), (False, True)] * 3
