"""M6 purchasing repositories against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from erp.modules.procurement.domain import (
    PaymentTerms,
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseRequisition,
    RequisitionStatus,
    RequisitionUrgency,
)
from erp.modules.procurement.infrastructure import (
    PurchaseOrderItemModel,
    PurchaseOrderModel,
    PurchaseOrderRepository,
    PurchaseRequisitionModel,
    PurchaseRequisitionRepository,
    RequisitionItemModel,
    SupplierRepository,
)
from erp.modules.product.domain import Product, ProductType
from erp.modules.product.infrastructure import ProductModel, ProductRepository
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError
from tests.integration.test_procurement_supplier_repository import (
    ProcurementFixture,
    procurement_fixture,
)

pytestmark = pytest.mark.integration


@asynccontextmanager
async def purchasing_fixture() -> AsyncIterator[tuple[ProcurementFixture, Product, Product]]:
    async with procurement_fixture() as data:
        product = Product.create(
            company_id=data.company_id,
            code=f"P{uuid4().hex[:12]}",
            sku=f"SKU{uuid4().hex[:12]}",
            name="Produto compras",
            product_type=ProductType.PA,
            uom="UN",
        )
        other_product = Product.create(
            company_id=data.other_company_id,
            code=f"P{uuid4().hex[:12]}",
            sku=f"SKU{uuid4().hex[:12]}",
            name="Produto externo",
            product_type=ProductType.PA,
            uom="UN",
        )
        async with data.database.session() as session, session.begin():
            await ProductRepository(session, company_id=data.company_id).add(
                product, actor_id=data.actor_id
            )
            await ProductRepository(session, company_id=data.other_company_id).add(
                other_product, actor_id=data.actor_id
            )
        try:
            yield data, product, other_product
        finally:
            async with data.database.session() as session, session.begin():
                company_ids = (data.company_id, data.other_company_id)
                await session.execute(
                    delete(PurchaseOrderItemModel).where(
                        PurchaseOrderItemModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(PurchaseOrderModel).where(PurchaseOrderModel.company_id.in_(company_ids))
                )
                await session.execute(
                    delete(RequisitionItemModel).where(
                        RequisitionItemModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(PurchaseRequisitionModel).where(
                        PurchaseRequisitionModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(ProductModel).where(ProductModel.company_id.in_(company_ids))
                )


def requisition(
    data: ProcurementFixture,
    product_id: UUID,
    *,
    company_id: UUID | None = None,
    number: str | None = None,
) -> PurchaseRequisition:
    return PurchaseRequisition.create(
        company_id=company_id or data.company_id,
        number=number or f"PR-{uuid4().hex[:10]}",
        requester_id=data.actor_id,
        cost_center_id=uuid4(),
        justification="Reposicao de estoque",
        lines=(
            (
                product_id,
                "10",
                "UN",
                datetime.now(UTC).date() + timedelta(days=7),
                RequisitionUrgency.HIGH,
                "Produto homologado",
            ),
        ),
    )


def order(
    data: ProcurementFixture, approved: PurchaseRequisition, supplier_id: UUID
) -> PurchaseOrder:
    item = approved.items[0]
    return PurchaseOrder.create_from_requisition(
        company_id=data.company_id,
        number=f"PO-{uuid4().hex[:10]}",
        supplier_id=supplier_id,
        source_requisition_id=approved.id,
        buyer_id=data.actor_id,
        currency_code="BRL",
        payment_terms=PaymentTerms.create(
            code="30D", description="Trinta dias", installment_days=(30,)
        ),
        lines=((item.id, item.product_id, item.quantity, Decimal("12.34"), "BRL"),),
    )


def test_requisition_round_trip_lifecycle_and_tenant_scope() -> None:
    async def scenario() -> None:
        async with purchasing_fixture() as (data, product, other_product):
            own = requisition(data, product.id)
            foreign = requisition(
                data, other_product.id, company_id=data.other_company_id, number=own.number
            )
            async with data.database.session() as session, session.begin():
                own_repo = PurchaseRequisitionRepository(session, company_id=data.company_id)
                foreign_repo = PurchaseRequisitionRepository(
                    session, company_id=data.other_company_id
                )
                await own_repo.add(own, actor_id=data.actor_id)
                await foreign_repo.add(foreign, actor_id=data.actor_id)
                submitted = own.submit()
                assert await own_repo.save(submitted, actor_id=data.actor_id) == submitted
                approved = submitted.approve()
                await own_repo.save(approved, actor_id=data.actor_id)
                assert await own_repo.get(own.id) == approved
                assert await own_repo.get(foreign.id) is None
                assert await own_repo.list(status=RequisitionStatus.APPROVED) == (approved,)
                assert await foreign_repo.list() == (foreign,)

    asyncio.run(scenario())


def test_requisition_rejects_cross_tenant_write_and_stale_version() -> None:
    async def scenario() -> None:
        async with purchasing_fixture() as (data, _, other_product):
            foreign = requisition(data, other_product.id, company_id=data.other_company_id)
            async with data.database.session() as session, session.begin():
                repository = PurchaseRequisitionRepository(session, company_id=data.company_id)
                with pytest.raises(ApplicationError, match="outside"):
                    await repository.add(foreign, actor_id=data.actor_id)
            own_product = Product.create(
                company_id=data.company_id,
                code=f"P{uuid4().hex[:12]}",
                sku=f"SKU{uuid4().hex[:12]}",
                name="Outro",
                product_type=ProductType.PA,
                uom="UN",
            )
            async with data.database.session() as session, session.begin():
                await ProductRepository(session, company_id=data.company_id).add(
                    own_product, actor_id=data.actor_id
                )
                draft = requisition(data, own_product.id)
                repo = PurchaseRequisitionRepository(session, company_id=data.company_id)
                await repo.add(draft, actor_id=data.actor_id)
                await repo.save(draft.submit(), actor_id=data.actor_id)
                with pytest.raises(OptimisticLockError):
                    await repo.save(draft.submit(), actor_id=data.actor_id)

    asyncio.run(scenario())


def test_purchase_order_round_trip_receipt_and_tenant_isolation() -> None:
    async def scenario() -> None:
        async with purchasing_fixture() as (data, product, _):
            supplier = data.supplier()
            draft_req = requisition(data, product.id)
            approved = draft_req.submit().approve()
            async with data.database.session() as session, session.begin():
                await SupplierRepository(session, company_id=data.company_id).add(
                    supplier, actor_id=data.actor_id
                )
                req_repo = PurchaseRequisitionRepository(session, company_id=data.company_id)
                await req_repo.add(draft_req, actor_id=data.actor_id)
                await req_repo.save(draft_req.submit(), actor_id=data.actor_id)
                await req_repo.save(approved, actor_id=data.actor_id)
                purchase_order = order(data, approved, supplier.id)
                repository = PurchaseOrderRepository(session, company_id=data.company_id)
                await repository.add(purchase_order, actor_id=data.actor_id)
                issued = purchase_order.submit_for_approval().approve().issue()
                for snapshot in (
                    purchase_order.submit_for_approval(),
                    purchase_order.submit_for_approval().approve(),
                    issued,
                ):
                    await repository.save(snapshot, actor_id=data.actor_id)
                received = issued.receive(((issued.items[0].id, "4"),))
                await repository.save(received, actor_id=data.actor_id)
                assert await repository.get(purchase_order.id) == received
                assert await repository.list(status=PurchaseOrderStatus.PARTIALLY_RECEIVED) == (
                    received,
                )
                assert (
                    await PurchaseOrderRepository(session, company_id=data.other_company_id).get(
                        purchase_order.id
                    )
                    is None
                )

    asyncio.run(scenario())
