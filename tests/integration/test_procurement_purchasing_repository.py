"""M6 purchasing repositories against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from erp.modules.procurement.domain import (
    PaymentTerms,
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseRequisition,
    RequisitionStatus,
    RequisitionUrgency,
)
from erp.modules.procurement.infrastructure import (
    APPROVAL_DECISION_MADE,
    ProcurementApprovalDecisionConsumer,
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
from erp.platform.audit import AuditEventModel
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError
from erp.platform.inbox import InboxEventModel
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxEventModel
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
                    delete(InboxEventModel).where(
                        InboxEventModel.consumer_name == "procurement.approval-decision.v1"
                    )
                )
                await session.execute(
                    delete(OutboxEventModel).where(
                        OutboxEventModel.payload["company_id"]
                        .as_string()
                        .in_(tuple(str(value) for value in company_ids))
                    )
                )
                await session.execute(
                    delete(AuditEventModel).where(AuditEventModel.company_id.in_(company_ids))
                )
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


def test_workflow_decision_is_consumed_exactly_once_with_outbox_effect() -> None:
    async def scenario() -> None:
        async with purchasing_fixture() as (data, product, _):
            supplier = data.supplier()
            draft = requisition(data, product.id)
            approved_requisition = draft.submit().approve()
            async with data.database.session() as session, session.begin():
                await SupplierRepository(session, company_id=data.company_id).add(
                    supplier, actor_id=data.actor_id
                )
                requisitions = PurchaseRequisitionRepository(session, company_id=data.company_id)
                await requisitions.add(draft, actor_id=data.actor_id)
                await requisitions.save(draft.submit(), actor_id=data.actor_id)
                await requisitions.save(approved_requisition, actor_id=data.actor_id)
                purchase_order = order(data, approved_requisition, supplier.id)
                orders = PurchaseOrderRepository(session, company_id=data.company_id)
                await orders.add(purchase_order, actor_id=data.actor_id)
                pending = purchase_order.submit_for_approval()
                await orders.save(pending, actor_id=data.actor_id)

            approver_id = uuid4()
            envelope = MessageEnvelope.new(
                message_kind=MessageKind.DOMAIN_EVENT,
                message_type=APPROVAL_DECISION_MADE,
                event_version=1,
                producer_module="workflow",
                producer_domain="workflow",
                aggregate_type="workflow_instance",
                aggregate_id=uuid4(),
                aggregate_version=2,
                company_id=data.company_id,
                branch_id=None,
                correlation_id=uuid4(),
                causation_id=None,
                request_id=uuid4(),
                payload={
                    "source_module": "procurement",
                    "source_type": "PURCHASE_ORDER",
                    "source_id": str(purchase_order.id),
                    "decision": "APPROVED",
                    "decided_by": str(approver_id),
                },
            )
            consumer = ProcurementApprovalDecisionConsumer(data.database)
            first = await consumer.consume(envelope)
            second = await consumer.consume(envelope)
            assert first.processed
            assert not first.duplicate
            assert second.duplicate
            assert not second.processed
            async with data.database.session() as session:
                persisted = await PurchaseOrderRepository(session, company_id=data.company_id).get(
                    purchase_order.id
                )
                assert persisted is not None
                assert persisted.status is PurchaseOrderStatus.APPROVED
                event_count = await session.scalar(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(
                        OutboxEventModel.aggregate_id == purchase_order.id,
                        OutboxEventModel.event_type == "PurchaseOrderApproved",
                    )
                )
                assert event_count == 1

    asyncio.run(scenario())
