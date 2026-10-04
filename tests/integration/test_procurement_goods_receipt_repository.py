"""M6 goods receipt repository integration against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect

from erp.modules.procurement.domain import (
    GoodsReceipt,
    GoodsReceiptStatus,
    InspectionDisposition,
    InventoryPostingConfirmation,
    PurchaseOrder,
    QualityInspectionResult,
    ReceiptTolerance,
)
from erp.modules.procurement.infrastructure import (
    GoodsReceiptConflictError,
    GoodsReceiptModel,
    GoodsReceiptRepository,
    PurchaseOrderRepository,
    PurchaseRequisitionRepository,
    ReceiptItemModel,
    SupplierRepository,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from tests.integration.test_procurement_purchasing_repository import (
    order,
    purchasing_fixture,
    requisition,
)
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


@asynccontextmanager
async def goods_receipt_fixture() -> AsyncIterator[tuple[ProcurementFixture, GoodsReceipt]]:
    async with purchasing_fixture() as (data, product, _):
        supplier = data.supplier()
        draft_requisition = requisition(data, product.id)
        approved_requisition = draft_requisition.submit().approve()
        purchase_order = order(data, approved_requisition, supplier.id)
        issued = purchase_order.submit_for_approval().approve().issue()
        async with data.database.session() as session, session.begin():
            await SupplierRepository(session, company_id=data.company_id).add(
                supplier, actor_id=data.actor_id
            )
            requisitions = PurchaseRequisitionRepository(session, company_id=data.company_id)
            await requisitions.add(draft_requisition, actor_id=data.actor_id)
            await requisitions.save(draft_requisition.submit(), actor_id=data.actor_id)
            await requisitions.save(approved_requisition, actor_id=data.actor_id)
            orders = PurchaseOrderRepository(session, company_id=data.company_id)
            await orders.add(purchase_order, actor_id=data.actor_id)
            await orders.save(purchase_order.submit_for_approval(), actor_id=data.actor_id)
            await orders.save(
                purchase_order.submit_for_approval().approve(), actor_id=data.actor_id
            )
            await orders.save(issued, actor_id=data.actor_id)
        receipt = GoodsReceipt.create_from_purchase_order(
            company_id=data.company_id,
            number=f"GR-{uuid4().hex[:10]}",
            purchase_order=issued,
            warehouse_id=uuid4(),
            received_by=data.actor_id,
            tolerance=ReceiptTolerance.create("5"),
            lines=((issued.items[0].id, "10", True, None, "LOT-001"),),
        )
        try:
            yield data, receipt
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(ReceiptItemModel).where(ReceiptItemModel.company_id == data.company_id)
                )
                await session.execute(
                    delete(GoodsReceiptModel).where(GoodsReceiptModel.company_id == data.company_id)
                )


def _approved(receipt: GoodsReceipt) -> GoodsReceipt:
    received = receipt.confirm_received()
    item = received.items[0]
    result = QualityInspectionResult.create(
        item=item,
        inspection_id=uuid4(),
        disposition=InspectionDisposition.APPROVE,
        approved_quantity=item.received_quantity,
    )
    return received.apply_inspection_results((result,))


def test_goods_receipt_round_trip_complete_lifecycle() -> None:
    async def scenario() -> None:
        async with (
            goods_receipt_fixture() as (data, draft),
            data.database.session() as session,
            session.begin(),
        ):
            repository = GoodsReceiptRepository(session, company_id=data.company_id)
            await repository.add(draft, actor_id=data.actor_id)
            assert await repository.get(draft.id) == draft

            received = draft.confirm_received()
            assert await repository.save(received, actor_id=data.actor_id) == received
            inspected = _approved(draft)
            await repository.save(inspected, actor_id=data.actor_id)
            confirmations = tuple(
                InventoryPostingConfirmation.create(
                    posting_request_id=request.id,
                    inventory_transaction_id=uuid4(),
                )
                for request in inspected.posting_requests
            )
            posted = inspected.confirm_inventory_posting(confirmations)
            await repository.save(posted, actor_id=data.actor_id)

            assert await repository.get(draft.id) == posted
            assert await repository.list(status=GoodsReceiptStatus.POSTED) == (posted,)
            assert await repository.list(purchase_order_id=draft.purchase_order_id) == (posted,)

    asyncio.run(scenario())


def test_partial_inspection_round_trip_preserves_m17_and_m5_contracts() -> None:
    async def scenario() -> None:
        async with (
            goods_receipt_fixture() as (data, draft),
            data.database.session() as session,
            session.begin(),
        ):
            repository = GoodsReceiptRepository(session, company_id=data.company_id)
            await repository.add(draft, actor_id=data.actor_id)
            received = draft.confirm_received()
            await repository.save(received, actor_id=data.actor_id)
            item = received.items[0]
            result = QualityInspectionResult.create(
                item=item,
                inspection_id=uuid4(),
                disposition=InspectionDisposition.PARTIAL_ACCEPTANCE,
                approved_quantity="7",
                quarantine_quantity="3",
                reason_code="QUALITY-HOLD",
            )
            inspected = received.apply_inspection_results((result,))
            await repository.save(inspected, actor_id=data.actor_id)
            assert await repository.get(draft.id) == inspected

            confirmations = tuple(
                InventoryPostingConfirmation.create(
                    posting_request_id=request.id,
                    inventory_transaction_id=uuid4(),
                )
                for request in inspected.posting_requests
            )
            posted = inspected.confirm_inventory_posting(confirmations)
            await repository.save(posted, actor_id=data.actor_id)
            assert await repository.get(draft.id) == posted

    asyncio.run(scenario())


def test_goods_receipt_is_tenant_bound_and_translates_duplicate_number() -> None:
    async def scenario() -> None:
        async with goods_receipt_fixture() as (data, draft):
            async with data.database.session() as session, session.begin():
                repository = GoodsReceiptRepository(session, company_id=data.company_id)
                await repository.add(draft, actor_id=data.actor_id)
                assert (
                    await GoodsReceiptRepository(session, company_id=data.other_company_id).get(
                        draft.id
                    )
                    is None
                )
                with pytest.raises(ApplicationError, match="outside"):
                    await GoodsReceiptRepository(session, company_id=data.other_company_id).add(
                        draft, actor_id=data.actor_id
                    )

            duplicate = GoodsReceipt.create_from_purchase_order(
                company_id=data.company_id,
                number=draft.number,
                purchase_order=await _load_order(data, draft.purchase_order_id),
                warehouse_id=uuid4(),
                received_by=data.actor_id,
                tolerance=ReceiptTolerance.create(),
                lines=((draft.items[0].purchase_order_item_id, "1", True, None, None),),
            )
            async with data.database.session() as session, session.begin():
                savepoint = await session.begin_nested()
                with pytest.raises(GoodsReceiptConflictError):
                    await GoodsReceiptRepository(session, company_id=data.company_id).add(
                        duplicate, actor_id=data.actor_id
                    )
                await savepoint.rollback()

    asyncio.run(scenario())


async def _load_order(data: ProcurementFixture, order_id: UUID) -> PurchaseOrder:
    async with data.database.session() as session:
        order = await PurchaseOrderRepository(session, company_id=data.company_id).get(order_id)
        assert order is not None
        return order


def test_goods_receipt_optimistic_lock_rejects_stale_writer() -> None:
    async def scenario() -> None:
        async with (
            goods_receipt_fixture() as (data, draft),
            data.database.session() as session,
            session.begin(),
        ):
            repository = GoodsReceiptRepository(session, company_id=data.company_id)
            await repository.add(draft, actor_id=data.actor_id)
            received = draft.confirm_received()
            await repository.save(received, actor_id=data.actor_id)
            with pytest.raises(OptimisticLockError):
                await repository.save(received, actor_id=data.actor_id, expected_version=1)

    asyncio.run(scenario())


def test_migration_0034_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def has_tables(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def verify(sync_connection: Connection) -> None:
                    tables = set(inspect(sync_connection).get_table_names(schema="procurement"))
                    assert ("goods_receipt" in tables) is expected
                    assert ("receipt_item" in tables) is expected

                await connection.run_sync(verify)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0033")
        asyncio.run(has_tables(False))
        command.upgrade(configuration, "0034")
        asyncio.run(has_tables(True))
    finally:
        command.upgrade(configuration, "head")
