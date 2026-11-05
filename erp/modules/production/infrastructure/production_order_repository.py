"""Tenant-bound persistence for complete production-order aggregates."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.production.domain import (
    EngineeringVersion,
    ProductionConflictError,
    ProductionEngineeringSnapshot,
    ProductionLotTrace,
    ProductionMaterialPlan,
    ProductionOperationStatus,
    ProductionOrder,
    ProductionOrderOperation,
    ProductionOrderStatus,
    ProductionQuantity,
    ProductionScopeError,
    ProductionVersionConflictError,
    UnitOfMeasure,
    WorkCenter,
    WorkCenterCode,
    WorkCenterConstraint,
)
from erp.modules.production.infrastructure.production_order_model import (
    ProductionOrderItemPlanModel,
    ProductionOrderModel,
    ProductionOrderOperationExecutionModel,
)


def _quantity_payload(trace: ProductionLotTrace) -> dict[str, str]:
    return {
        "lot_id": str(trace.lot_id),
        "product_id": str(trace.product_id),
        "quantity": str(trace.quantity.amount),
        "uom": trace.quantity.unit.value,
    }


def _lot_trace(payload: dict[str, str]) -> ProductionLotTrace:
    return ProductionLotTrace(
        lot_id=UUID(payload["lot_id"]),
        product_id=UUID(payload["product_id"]),
        quantity=ProductionQuantity(
            Decimal(payload["quantity"]),
            UnitOfMeasure(payload["uom"]),
        ),
    )


def _production_order(
    header: ProductionOrderModel,
    materials: tuple[ProductionOrderItemPlanModel, ...],
    operations: tuple[ProductionOrderOperationExecutionModel, ...],
) -> ProductionOrder:
    engineering = ProductionEngineeringSnapshot(
        company_id=header.company_id,
        product_id=header.product_id,
        bom_version=EngineeringVersion(
            header.bom_version_code,
            header.bom_engineering_revision,
            header.bom_effective_from,
            header.bom_effective_until,
        ),
        bom_record_version=header.bom_record_version,
        routing_version=EngineeringVersion(
            header.routing_version_code,
            header.routing_engineering_revision,
            header.routing_effective_from,
            header.routing_effective_until,
        ),
        routing_record_version=header.routing_record_version,
        bom_output_quantity=ProductionQuantity(
            header.engineering_output_quantity,
            UnitOfMeasure(header.engineering_output_uom),
        ),
        approved_at=header.engineering_approved_at,
        approved_by=header.engineering_approved_by,
    )
    return ProductionOrder(
        id=header.id,
        company_id=header.company_id,
        order_number=header.order_number,
        product_id=header.product_id,
        planned_quantity=ProductionQuantity(
            header.planned_quantity,
            UnitOfMeasure(header.planned_uom),
        ),
        planned_start_on=header.planned_start_on,
        due_on=header.due_on,
        engineering=engineering,
        materials=tuple(
            ProductionMaterialPlan(
                product_id=item.component_product_id,
                planned_quantity=ProductionQuantity(
                    item.planned_quantity,
                    UnitOfMeasure(item.uom),
                ),
                consumptions=tuple(_lot_trace(value) for value in item.consumptions),
            )
            for item in materials
        ),
        operations=tuple(_operation(header.company_id, item) for item in operations),
        created_at=header.created_at,
        created_by=header.created_by,
        status=ProductionOrderStatus(header.status),
        output_lots=tuple(_lot_trace(value) for value in header.output_lots),
        released_at=header.released_at,
        released_by=header.released_by,
        started_at=header.started_at,
        started_by=header.started_by,
        completed_at=header.completed_at,
        completed_by=header.completed_by,
        cancelled_at=header.cancelled_at,
        cancelled_by=header.cancelled_by,
        cancellation_reason=header.cancellation_reason,
        record_version=header.version,
    )


def _operation(
    company_id: UUID,
    model: ProductionOrderOperationExecutionModel,
) -> ProductionOrderOperation:
    assigned = None
    if model.assigned_work_center_code is not None:
        assigned = WorkCenter(
            company_id=company_id,
            code=WorkCenterCode(model.assigned_work_center_code),
            capabilities=frozenset(model.assigned_work_center_capabilities or ()),
            record_version=model.assigned_work_center_version or 1,
        )
    return ProductionOrderOperation(
        sequence=model.sequence,
        name=model.name,
        work_center=WorkCenterConstraint(
            company_id=company_id,
            allowed_centers=tuple(
                WorkCenterCode(code) for code in model.allowed_work_centers
            ),
            required_capabilities=frozenset(model.required_capabilities),
        ),
        status=ProductionOperationStatus(model.status),
        assigned_work_center=assigned,
        started_at=model.started_at,
        started_by=model.started_by,
        completed_at=model.completed_at,
        completed_by=model.completed_by,
    )


class ProductionOrderRepository:
    """Persist complete production orders without owning transaction boundaries."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(
        self,
        aggregate: ProductionOrder,
        *,
        actor_id: UUID,
    ) -> ProductionOrder:
        self._validate_write(aggregate, actor_id)
        if aggregate.record_version != 1:
            raise ValueError("A new production order must start at record_version one.")
        self._session.add(ProductionOrderModel(**self._header_values(aggregate, actor_id)))
        await self._flush_conflict()
        self._add_children(aggregate)
        await self._flush_conflict()
        return aggregate

    async def get(self, order_id: UUID) -> ProductionOrder | None:
        self._uuid(order_id, "order_id")
        result = await self._session.scalars(
            select(ProductionOrderModel)
            .where(
                ProductionOrderModel.company_id == self._company_id,
                ProductionOrderModel.id == order_id,
            )
            .execution_options(populate_existing=True)
        )
        header = result.one_or_none()
        if header is None:
            return None
        return _production_order(
            header,
            await self._materials(header.id),
            await self._operations(header.id),
        )

    async def save(
        self,
        aggregate: ProductionOrder,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> ProductionOrder:
        self._validate_write(aggregate, actor_id)
        self._validate_next_version(aggregate.record_version, expected_version)
        try:
            result = await self._session.execute(
                update(ProductionOrderModel)
                .where(
                    ProductionOrderModel.company_id == self._company_id,
                    ProductionOrderModel.id == aggregate.id,
                    ProductionOrderModel.version == expected_version,
                )
                .values(**self._mutable_header_values(aggregate, actor_id))
                .returning(ProductionOrderModel.id)
                .execution_options(synchronize_session=False)
            )
        except IntegrityError as error:
            self._raise_conflict(error)
        if result.scalar_one_or_none() is None:
            raise ProductionVersionConflictError(expected_version)
        await self._session.execute(
            delete(ProductionOrderItemPlanModel).where(
                ProductionOrderItemPlanModel.company_id == self._company_id,
                ProductionOrderItemPlanModel.production_order_id == aggregate.id,
            )
        )
        await self._session.execute(
            delete(ProductionOrderOperationExecutionModel).where(
                ProductionOrderOperationExecutionModel.company_id == self._company_id,
                ProductionOrderOperationExecutionModel.production_order_id == aggregate.id,
            )
        )
        self._add_children(aggregate)
        await self._flush_conflict()
        return aggregate

    async def _materials(
        self,
        order_id: UUID,
    ) -> tuple[ProductionOrderItemPlanModel, ...]:
        result = await self._session.scalars(
            select(ProductionOrderItemPlanModel)
            .where(
                ProductionOrderItemPlanModel.company_id == self._company_id,
                ProductionOrderItemPlanModel.production_order_id == order_id,
            )
            .order_by(ProductionOrderItemPlanModel.sequence)
            .execution_options(populate_existing=True)
        )
        return tuple(result)

    async def _operations(
        self,
        order_id: UUID,
    ) -> tuple[ProductionOrderOperationExecutionModel, ...]:
        result = await self._session.scalars(
            select(ProductionOrderOperationExecutionModel)
            .where(
                ProductionOrderOperationExecutionModel.company_id == self._company_id,
                ProductionOrderOperationExecutionModel.production_order_id == order_id,
            )
            .order_by(ProductionOrderOperationExecutionModel.sequence)
            .execution_options(populate_existing=True)
        )
        return tuple(result)

    def _add_children(self, aggregate: ProductionOrder) -> None:
        self._session.add_all(
            [
                ProductionOrderItemPlanModel(
                    id=uuid4(),
                    company_id=self._company_id,
                    production_order_id=aggregate.id,
                    sequence=sequence,
                    component_product_id=plan.product_id,
                    planned_quantity=plan.planned_quantity.amount,
                    uom=plan.planned_quantity.unit.value,
                    consumptions=[_quantity_payload(item) for item in plan.consumptions],
                    version=1,
                )
                for sequence, plan in enumerate(aggregate.materials, start=1)
            ]
        )
        self._session.add_all(
            [
                ProductionOrderOperationExecutionModel(
                    id=uuid4(),
                    company_id=self._company_id,
                    production_order_id=aggregate.id,
                    sequence=operation.sequence,
                    name=operation.name,
                    status=operation.status.value,
                    allowed_work_centers=[
                        code.value for code in operation.work_center.allowed_centers
                    ],
                    required_capabilities=sorted(
                        operation.work_center.required_capabilities
                    ),
                    assigned_work_center_code=(
                        operation.assigned_work_center.code.value
                        if operation.assigned_work_center is not None
                        else None
                    ),
                    assigned_work_center_capabilities=(
                        sorted(operation.assigned_work_center.capabilities)
                        if operation.assigned_work_center is not None
                        else None
                    ),
                    assigned_work_center_version=(
                        operation.assigned_work_center.record_version
                        if operation.assigned_work_center is not None
                        else None
                    ),
                    started_at=operation.started_at,
                    started_by=operation.started_by,
                    completed_at=operation.completed_at,
                    completed_by=operation.completed_by,
                    version=1,
                )
                for operation in aggregate.operations
            ]
        )

    def _header_values(
        self,
        aggregate: ProductionOrder,
        actor_id: UUID,
    ) -> dict[str, Any]:
        return {
            "id": aggregate.id,
            "company_id": self._company_id,
            "created_at": aggregate.created_at,
            "created_by": aggregate.created_by,
            **self._mutable_header_values(aggregate, actor_id),
        }

    @staticmethod
    def _mutable_header_values(
        aggregate: ProductionOrder,
        actor_id: UUID,
    ) -> dict[str, Any]:
        engineering = aggregate.engineering
        return {
            "order_number": aggregate.order_number,
            "product_id": aggregate.product_id,
            "status": aggregate.status.value,
            "planned_quantity": aggregate.planned_quantity.amount,
            "planned_uom": aggregate.planned_quantity.unit.value,
            "planned_start_on": aggregate.planned_start_on,
            "due_on": aggregate.due_on,
            "bom_version_code": engineering.bom_version.code,
            "bom_engineering_revision": engineering.bom_version.revision,
            "bom_effective_from": engineering.bom_version.effective_from,
            "bom_effective_until": engineering.bom_version.effective_until,
            "bom_record_version": engineering.bom_record_version,
            "routing_version_code": engineering.routing_version.code,
            "routing_engineering_revision": engineering.routing_version.revision,
            "routing_effective_from": engineering.routing_version.effective_from,
            "routing_effective_until": engineering.routing_version.effective_until,
            "routing_record_version": engineering.routing_record_version,
            "engineering_output_quantity": engineering.bom_output_quantity.amount,
            "engineering_output_uom": engineering.bom_output_quantity.unit.value,
            "engineering_approved_at": engineering.approved_at,
            "engineering_approved_by": engineering.approved_by,
            "output_lots": [_quantity_payload(item) for item in aggregate.output_lots],
            "released_at": aggregate.released_at,
            "released_by": aggregate.released_by,
            "started_at": aggregate.started_at,
            "started_by": aggregate.started_by,
            "completed_at": aggregate.completed_at,
            "completed_by": aggregate.completed_by,
            "cancelled_at": aggregate.cancelled_at,
            "cancelled_by": aggregate.cancelled_by,
            "cancellation_reason": aggregate.cancellation_reason,
            "version": aggregate.record_version,
            "updated_at": datetime.now(UTC),
            "updated_by": actor_id,
        }

    def _validate_write(self, aggregate: ProductionOrder, actor_id: UUID) -> None:
        if not isinstance(aggregate, ProductionOrder):
            raise TypeError("aggregate must be a ProductionOrder.")
        if aggregate.company_id != self._company_id:
            raise ProductionScopeError("production order belongs to another company.")
        self._uuid(actor_id, "actor_id")

    @staticmethod
    def _validate_next_version(record_version: int, expected_version: int) -> None:
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected_version must be a positive integer.")
        if record_version != expected_version + 1:
            raise ValueError("save requires exactly one new record version.")

    @staticmethod
    def _uuid(value: UUID, field: str) -> None:
        if not isinstance(value, UUID) or value.int == 0:
            raise ValueError(f"{field} must be a non-zero UUID.")

    async def _flush_conflict(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            self._raise_conflict(error)

    @staticmethod
    def _raise_conflict(error: IntegrityError) -> None:
        if getattr(error.orig, "sqlstate", None) in {"23503", "23505", "23514"}:
            raise ProductionConflictError(
                "Production order conflicts with engineering, product or tenant constraints."
            ) from error
        raise error


__all__ = ["ProductionOrderRepository", "_production_order"]
