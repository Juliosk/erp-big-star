"""Cross-module M11/M6/M17/M5 fiscal receiving reconciliation."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import Connection, delete, inspect, select

from erp.modules.admin.contracts import CompanyAccessService
from erp.modules.admin.infrastructure import PostgresCorporateDirectory
from erp.modules.fiscal.application import (
    FISCAL_INBOUND_MANAGE,
    FISCAL_INBOUND_READ,
    FiscalAuthorization,
    InboundFiscalDocumentService,
)
from erp.modules.fiscal.infrastructure import (
    FiscalReceivingReconciliationModel,
    InboundFiscalDocumentItemModel,
    InboundFiscalDocumentModel,
    MdeEventModel,
    PostgresInboundFiscalOperations,
    SefazMockAdapter,
)
from erp.modules.inventory.infrastructure.balance_model import InventoryBalanceModel
from erp.modules.procurement.infrastructure import GoodsReceiptModel
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.idempotency import IdempotencyRecordModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_procurement_goods_receipt_api import (
    _create_receipt,
    _mutate,
    goods_receipt_api,
)
from tests.integration.test_procurement_purchasing_api import (
    action,
    approve_requisition,
    create_order,
    create_supplier,
)
from tests.unit.modules.fiscal.application.test_inbound_fiscal import inbound_xml

pytestmark = pytest.mark.integration


@contextmanager
def reconciliation_api() -> Iterator[tuple[Any, Any, Any, Any]]:
    with goods_receipt_api() as (api, warehouse):
        assert api.resolver.context is not None
        api.resolver.context = replace(
            api.resolver.context,
            permissions=api.resolver.context.permissions
            | {FISCAL_INBOUND_READ, FISCAL_INBOUND_MANAGE},
        )
        application = cast(FastAPI, api.client.app)
        application.state.inbound_fiscal_documents = InboundFiscalDocumentService(
            PostgresInboundFiscalOperations(
                api.data.database, SefazMockAdapter(), ttl_seconds=3600
            ),
            FiscalAuthorization(
                CompanyAccessService(PostgresCorporateDirectory(api.data.database))
            ),
        )
        requisition = approve_requisition(api)
        supplier = create_supplier(api)
        order = create_order(api, requisition, supplier)
        submitted = action(
            api, "purchase-orders", order.json()["id"], "submit", order.headers["etag"]
        )
        approved = action(
            api,
            "purchase-orders",
            order.json()["id"],
            "approve",
            submitted.headers["etag"],
        )
        issued = action(
            api, "purchase-orders", order.json()["id"], "issue", approved.headers["etag"]
        )
        try:
            yield api, warehouse, issued, supplier
        finally:

            async def cleanup() -> None:
                async with api.data.database.session() as session, session.begin():
                    await session.execute(
                        delete(FiscalReceivingReconciliationModel).where(
                            FiscalReceivingReconciliationModel.company_id == api.data.company_id
                        )
                    )
                    await session.execute(
                        delete(MdeEventModel).where(MdeEventModel.company_id == api.data.company_id)
                    )
                    await session.execute(
                        delete(InboundFiscalDocumentItemModel).where(
                            InboundFiscalDocumentItemModel.company_id == api.data.company_id
                        )
                    )
                    await session.execute(
                        delete(InboundFiscalDocumentModel).where(
                            InboundFiscalDocumentModel.company_id == api.data.company_id
                        )
                    )
                    await session.execute(
                        delete(IdempotencyRecordModel).where(
                            IdempotencyRecordModel.scope.like(f"fiscal-%:{api.data.company_id}:%")
                        )
                    )
                    await session.execute(
                        delete(OutboxEventModel).where(
                            OutboxEventModel.aggregate_type == "fiscal_receiving_reconciliation"
                        )
                    )
                    await session.execute(
                        delete(AuditEventModel).where(
                            AuditEventModel.company_id == api.data.company_id,
                            AuditEventModel.entity_type == "fiscal_receiving_reconciliation",
                        )
                    )

            assert api.client.portal is not None
            api.client.portal.call(cleanup)


def _inspected_receipt(api: Any, warehouse: Any, issued: Any) -> Any:
    created = _create_receipt(api, warehouse, issued)
    received = _mutate(api, created, "receive", {})
    item = received.json()["items"][0]
    return _mutate(
        api,
        received,
        "inspect",
        {
            "decisions": [
                {
                    "receipt_item_id": item["id"],
                    "inspection_id": str(uuid4()),
                    "disposition": "APPROVE",
                    "approved_quantity": "10",
                }
            ]
        },
    )


def _xml(
    supplier_tax_id: str,
    *,
    quantity: str = "10.0000",
    price: str = "12.34",
    total: str = "123.40",
) -> str:
    return (
        inbound_xml()
        .replace("<emit><CNPJ>12345678000195</CNPJ>", f"<emit><CNPJ>{supplier_tax_id}</CNPJ>")
        .replace("<qCom>2.0000</qCom>", f"<qCom>{quantity}</qCom>")
        .replace("<vUnCom>10.00</vUnCom>", f"<vUnCom>{price}</vUnCom>")
        .replace("<vProd>20.00</vProd>", f"<vProd>{total}</vProd>")
        .replace("<vNF>20.00</vNF>", f"<vNF>{total}</vNF>")
    )


def _upload(
    api: Any,
    supplier: Any,
    *,
    quantity: str = "10.0000",
    price: str = "12.34",
    total: str = "123.40",
) -> Any:
    return api.client.post(
        f"/api/v1/fiscal/inbound-documents/upload?company_id={api.data.company_id}",
        content=_xml(
            supplier.json()["identity_value"],
            quantity=quantity,
            price=price,
            total=total,
        ),
        headers={
            **api.headers,
            "Content-Type": "application/xml",
            "Idempotency-Key": str(uuid4()),
        },
    )


def _reconcile(api: Any, inbound: Any, receipt: Any, *, key: str | None = None) -> Any:
    return api.client.post(
        f"/api/v1/fiscal/inbound-documents/{inbound.json()['id']}/reconcile"
        f"?company_id={api.data.company_id}",
        headers={
            **api.headers,
            "If-Match": inbound.headers["etag"],
            "Idempotency-Key": key or str(uuid4()),
        },
        json={
            "goods_receipt_id": receipt.json()["id"],
            "line_mappings": [
                {
                    "inbound_line_number": 1,
                    "receipt_item_id": receipt.json()["items"][0]["id"],
                }
            ],
        },
    )


def test_matching_inbound_and_inspected_receipt_posts_available_atomically() -> None:
    with reconciliation_api() as (api, warehouse, issued, supplier):
        receipt = _inspected_receipt(api, warehouse, issued)
        inbound = _upload(api, supplier)
        assert inbound.status_code == 201, inbound.text
        key = str(uuid4())
        reconciled = _reconcile(api, inbound, receipt, key=key)
        assert reconciled.status_code == 200, reconciled.text
        assert reconciled.json()["status"] == "POSTED"
        assert reconciled.json()["issues"] == []
        assert reconciled.json()["financial_blocked"] is False
        assert len(reconciled.json()["inventory_transaction_ids"]) == 1
        replay = _reconcile(api, inbound, receipt, key=key)
        assert replay.status_code == 200
        assert replay.headers["idempotency-replayed"] == "true"
        assert replay.json()["id"] == reconciled.json()["id"]

        async def verify() -> tuple[str, str, int]:
            async with api.data.database.session() as session:
                balance = await session.scalar(
                    select(InventoryBalanceModel).where(
                        InventoryBalanceModel.company_id == api.data.company_id,
                        InventoryBalanceModel.product_id
                        == UUID(receipt.json()["items"][0]["product_id"]),
                        InventoryBalanceModel.state == "AVAILABLE",
                    )
                )
                stored_receipt = await session.scalar(
                    select(GoodsReceiptModel).where(
                        GoodsReceiptModel.company_id == api.data.company_id,
                        GoodsReceiptModel.id == UUID(receipt.json()["id"]),
                    )
                )
                event_count = len(
                    tuple(
                        await session.scalars(
                            select(OutboxEventModel).where(
                                OutboxEventModel.aggregate_type
                                == "fiscal_receiving_reconciliation",
                                OutboxEventModel.aggregate_id == UUID(reconciled.json()["id"]),
                            )
                        )
                    )
                )
                assert balance is not None
                assert stored_receipt is not None
                return stored_receipt.status, str(balance.quantity), event_count

        assert api.client.portal is not None
        status, quantity, event_count = api.client.portal.call(verify)
        assert status == "POSTED"
        assert quantity == "10.000000"
        assert event_count == 1


def test_price_divergence_blocks_financial_and_inventory_posting() -> None:
    with reconciliation_api() as (api, warehouse, issued, supplier):
        receipt = _inspected_receipt(api, warehouse, issued)
        inbound = _upload(api, supplier, price="13.34", total="133.40")
        result = _reconcile(api, inbound, receipt)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "DIVERGENT"
        assert result.json()["financial_blocked"] is True
        assert result.json()["inventory_transaction_ids"] == []
        assert {value["kind"] for value in result.json()["issues"]} == {
            "UNIT_PRICE_MISMATCH",
            "FISCAL_TOTAL_MISMATCH",
        }


def test_quantity_divergence_creates_physical_pending_without_posting() -> None:
    with reconciliation_api() as (api, warehouse, issued, supplier):
        receipt = _inspected_receipt(api, warehouse, issued)
        inbound = _upload(api, supplier, quantity="9.0000", total="111.06")
        result = _reconcile(api, inbound, receipt)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "DIVERGENT"
        assert result.json()["physical_pending"] is True
        assert result.json()["financial_blocked"] is False
        assert result.json()["inventory_transaction_ids"] == []
        assert {value["kind"] for value in result.json()["issues"]} == {"QUANTITY_MISMATCH"}


def test_migration_0038_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def schema(sync_connection: Connection) -> None:
                    tables = set(inspect(sync_connection).get_table_names(schema="fiscal"))
                    assert ("receiving_reconciliation" in tables) is expected

                await connection.run_sync(schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0037")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0038")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")
