"""Tenant-bound repositories for M6 purchase requisitions and orders."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.domain import (
    PaymentTerms,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    PurchaseRequisition,
    RequisitionItem,
    RequisitionStatus,
    RequisitionUrgency,
)
from erp.modules.procurement.infrastructure.purchasing_model import (
    PurchaseOrderItemModel,
    PurchaseOrderModel,
    PurchaseRequisitionModel,
    RequisitionItemModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


class PurchaseRequisitionConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="PURCHASE_REQUISITION_CONFLICT",
            message="A purchase requisition number already exists for this company.",
            status_code=409,
        )


class PurchaseOrderConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="PURCHASE_ORDER_CONFLICT",
            message="A purchase order number already exists for this company.",
            status_code=409,
        )


def _requisition(
    model: PurchaseRequisitionModel, items: tuple[RequisitionItemModel, ...]
) -> PurchaseRequisition:
    return PurchaseRequisition(
        id=model.id,
        company_id=model.company_id,
        number=model.number,
        requester_id=model.requester_id,
        cost_center_id=model.cost_center_id,
        status=RequisitionStatus(model.status),
        items=tuple(
            RequisitionItem(
                id=item.id,
                company_id=item.company_id,
                requisition_id=item.requisition_id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_of_measure=item.unit_of_measure,
                needed_by=item.needed_by,
                urgency=RequisitionUrgency(item.urgency),
                specification=item.specification,
            )
            for item in items
        ),
        justification=model.justification,
        version=model.version,
    )


def _order(model: PurchaseOrderModel, items: tuple[PurchaseOrderItemModel, ...]) -> PurchaseOrder:
    return PurchaseOrder(
        id=model.id,
        company_id=model.company_id,
        number=model.number,
        supplier_id=model.supplier_id,
        source_requisition_id=model.source_requisition_id,
        buyer_id=model.buyer_id,
        currency=model.currency,
        payment_terms=PaymentTerms(
            model.payment_terms_code,
            model.payment_terms_description,
            tuple(model.payment_installment_days),
        ),
        status=PurchaseOrderStatus(model.status),
        items=tuple(
            PurchaseOrderItem(
                id=item.id,
                company_id=item.company_id,
                purchase_order_id=item.purchase_order_id,
                requisition_item_id=item.requisition_item_id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
                currency=item.currency,
                received_quantity=item.received_quantity,
            )
            for item in items
        ),
        total_amount=model.total_amount,
        version=model.version,
    )


class _TenantRepository:
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    def _write(self, company_id: UUID, actor_id: UUID) -> None:
        if company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The resource is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    @staticmethod
    def _page(limit: int, offset: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100.")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer.")


class PurchaseRequisitionRepository(_TenantRepository):
    async def add(self, requisition: PurchaseRequisition, *, actor_id: UUID) -> None:
        self._write(requisition.company_id, actor_id)
        if requisition.version != 1 or requisition.status is not RequisitionStatus.DRAFT:
            raise ValueError("A new requisition must start draft at version one.")
        if any(
            item.company_id != self._company_id or item.requisition_id != requisition.id
            for item in requisition.items
        ):
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="A requisition item is outside the aggregate scope.",
                status_code=403,
            )
        self._session.add(
            PurchaseRequisitionModel(
                id=requisition.id,
                company_id=self._company_id,
                number=requisition.number,
                requester_id=requisition.requester_id,
                cost_center_id=requisition.cost_center_id,
                status=requisition.status,
                justification=requisition.justification,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        self._session.add_all(
            [
                RequisitionItemModel(
                    id=item.id,
                    company_id=self._company_id,
                    requisition_id=requisition.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_of_measure=item.unit_of_measure,
                    needed_by=item.needed_by,
                    urgency=item.urgency,
                    specification=item.specification,
                    created_by=actor_id,
                )
                for item in requisition.items
            ]
        )
        await self._flush(PurchaseRequisitionConflictError)

    async def get(self, requisition_id: UUID) -> PurchaseRequisition | None:
        model = await self._session.scalar(
            select(PurchaseRequisitionModel)
            .where(
                PurchaseRequisitionModel.company_id == self._company_id,
                PurchaseRequisitionModel.id == requisition_id,
            )
            .execution_options(populate_existing=True)
        )
        if model is None:
            return None
        items = await self._session.scalars(
            select(RequisitionItemModel)
            .where(
                RequisitionItemModel.company_id == self._company_id,
                RequisitionItemModel.requisition_id == requisition_id,
            )
            .order_by(RequisitionItemModel.id)
        )
        return _requisition(model, tuple(items))

    async def list(
        self,
        *,
        status: RequisitionStatus | None = None,
        cost_center_id: UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PurchaseRequisition, ...]:
        self._page(limit, offset)
        statement = select(PurchaseRequisitionModel).where(
            PurchaseRequisitionModel.company_id == self._company_id
        )
        if status is not None:
            if not isinstance(status, RequisitionStatus):
                raise ValueError("status must be an official requisition status.")
            statement = statement.where(PurchaseRequisitionModel.status == status)
        if cost_center_id is not None:
            statement = statement.where(PurchaseRequisitionModel.cost_center_id == cost_center_id)
        if created_from is not None:
            statement = statement.where(PurchaseRequisitionModel.created_at >= created_from)
        if created_to is not None:
            statement = statement.where(PurchaseRequisitionModel.created_at <= created_to)
        models = await self._session.scalars(
            statement.order_by(PurchaseRequisitionModel.number, PurchaseRequisitionModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        result = []
        for model in models:
            items = await self._session.scalars(
                select(RequisitionItemModel)
                .where(
                    RequisitionItemModel.company_id == self._company_id,
                    RequisitionItemModel.requisition_id == model.id,
                )
                .order_by(RequisitionItemModel.id)
            )
            result.append(_requisition(model, tuple(items)))
        return tuple(result)

    async def save(
        self,
        requisition: PurchaseRequisition,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> PurchaseRequisition:
        self._write(requisition.company_id, actor_id)
        compare = requisition.version - 1 if expected_version is None else expected_version
        if compare < 1 or requisition.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(PurchaseRequisitionModel)
                .where(
                    PurchaseRequisitionModel.company_id == self._company_id,
                    PurchaseRequisitionModel.id == requisition.id,
                    PurchaseRequisitionModel.version == compare,
                    PurchaseRequisitionModel.number == requisition.number,
                    PurchaseRequisitionModel.requester_id == requisition.requester_id,
                    PurchaseRequisitionModel.cost_center_id == requisition.cost_center_id,
                )
                .values(
                    status=requisition.status,
                    version=requisition.version,
                    updated_at=datetime.now(UTC),
                    updated_by=actor_id,
                )
            ),
        )
        if result.rowcount != 1:
            raise OptimisticLockError(expected_version=compare)
        await self._session.flush()
        return requisition

    async def _flush(self, conflict: Callable[[], ApplicationError]) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise conflict() from error
            raise


class PurchaseOrderRepository(_TenantRepository):
    async def add(self, order: PurchaseOrder, *, actor_id: UUID) -> None:
        self._write(order.company_id, actor_id)
        if order.version != 1 or order.status is not PurchaseOrderStatus.DRAFT:
            raise ValueError("A new purchase order must start draft at version one.")
        if any(
            item.company_id != self._company_id or item.purchase_order_id != order.id
            for item in order.items
        ):
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="A purchase order item is outside the aggregate scope.",
                status_code=403,
            )
        self._session.add(
            PurchaseOrderModel(
                id=order.id,
                company_id=self._company_id,
                number=order.number,
                supplier_id=order.supplier_id,
                source_requisition_id=order.source_requisition_id,
                buyer_id=order.buyer_id,
                currency=order.currency,
                payment_terms_code=order.payment_terms.code,
                payment_terms_description=order.payment_terms.description,
                payment_installment_days=list(order.payment_terms.installment_days),
                status=order.status,
                total_amount=order.total_amount,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        self._session.add_all(
            [
                PurchaseOrderItemModel(
                    id=item.id,
                    company_id=self._company_id,
                    purchase_order_id=order.id,
                    requisition_item_id=item.requisition_item_id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    currency=item.currency,
                    received_quantity=item.received_quantity,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                for item in order.items
            ]
        )
        await self._flush()

    async def get(self, order_id: UUID) -> PurchaseOrder | None:
        model = await self._session.scalar(
            select(PurchaseOrderModel)
            .where(
                PurchaseOrderModel.company_id == self._company_id, PurchaseOrderModel.id == order_id
            )
            .execution_options(populate_existing=True)
        )
        if model is None:
            return None
        return _order(model, await self._items(order_id))

    async def list(
        self,
        *,
        status: PurchaseOrderStatus | None = None,
        supplier_id: UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[PurchaseOrder, ...]:
        self._page(limit, offset)
        statement = select(PurchaseOrderModel).where(
            PurchaseOrderModel.company_id == self._company_id
        )
        if status is not None:
            if not isinstance(status, PurchaseOrderStatus):
                raise ValueError("status must be an official purchase order status.")
            statement = statement.where(PurchaseOrderModel.status == status)
        if supplier_id is not None:
            statement = statement.where(PurchaseOrderModel.supplier_id == supplier_id)
        if created_from is not None:
            statement = statement.where(PurchaseOrderModel.created_at >= created_from)
        if created_to is not None:
            statement = statement.where(PurchaseOrderModel.created_at <= created_to)
        models = await self._session.scalars(
            statement.order_by(PurchaseOrderModel.number, PurchaseOrderModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        result = []
        for model in models:
            result.append(_order(model, await self._items(model.id)))
        return tuple(result)

    async def save(
        self, order: PurchaseOrder, *, actor_id: UUID, expected_version: int | None = None
    ) -> PurchaseOrder:
        self._write(order.company_id, actor_id)
        compare = order.version - 1 if expected_version is None else expected_version
        if compare < 1 or order.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(PurchaseOrderModel)
                .where(
                    PurchaseOrderModel.company_id == self._company_id,
                    PurchaseOrderModel.id == order.id,
                    PurchaseOrderModel.version == compare,
                    PurchaseOrderModel.number == order.number,
                    PurchaseOrderModel.supplier_id == order.supplier_id,
                    PurchaseOrderModel.source_requisition_id == order.source_requisition_id,
                )
                .values(
                    status=order.status,
                    version=order.version,
                    updated_at=datetime.now(UTC),
                    updated_by=actor_id,
                )
            ),
        )
        if result.rowcount != 1:
            raise OptimisticLockError(expected_version=compare)
        for item in order.items:
            updated = cast(
                CursorResult[Any],
                await self._session.execute(
                    update(PurchaseOrderItemModel)
                    .where(
                        PurchaseOrderItemModel.company_id == self._company_id,
                        PurchaseOrderItemModel.purchase_order_id == order.id,
                        PurchaseOrderItemModel.id == item.id,
                    )
                    .values(
                        received_quantity=item.received_quantity,
                        updated_at=datetime.now(UTC),
                        updated_by=actor_id,
                    )
                ),
            )
            if updated.rowcount != 1:
                raise ApplicationError(
                    code="PURCHASE_ORDER_ITEM_NOT_FOUND",
                    message="A purchase order item no longer exists.",
                    status_code=409,
                )
        await self._session.flush()
        return order

    async def _items(self, order_id: UUID) -> tuple[PurchaseOrderItemModel, ...]:
        items = await self._session.scalars(
            select(PurchaseOrderItemModel)
            .where(
                PurchaseOrderItemModel.company_id == self._company_id,
                PurchaseOrderItemModel.purchase_order_id == order_id,
            )
            .order_by(PurchaseOrderItemModel.id)
        )
        return tuple(items)

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise PurchaseOrderConflictError from error
            raise


__all__ = [
    "PurchaseOrderConflictError",
    "PurchaseOrderRepository",
    "PurchaseRequisitionConflictError",
    "PurchaseRequisitionRepository",
    "_order",
    "_requisition",
]
