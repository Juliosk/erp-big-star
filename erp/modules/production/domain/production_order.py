"""Immutable Production Order aggregate and manufacturing lifecycle."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from erp.modules.production.domain.bom import BillOfMaterials, MaterialRequirement
from erp.modules.production.domain.exceptions import (
    EngineeringUnavailableError,
    InvalidProductionOrderStateError,
    InvalidProductionValueError,
    LotTraceabilityError,
    ProductionQuantityExceededError,
    ProductionScopeError,
    RoutingConsistencyError,
    UnitOfMeasureMismatchError,
)
from erp.modules.production.domain.production_order_values import (
    ProductionEngineeringSnapshot,
    ProductionLotTrace,
    ProductionMaterialPlan,
    ProductionOperationStatus,
    ProductionOrderOperation,
    ProductionOrderStatus,
    _aware_datetime,
    _date,
)
from erp.modules.production.domain.routing import ProductionRouting, WorkCenter
from erp.modules.production.domain.values import ProductionQuantity, require_uuid


def _order_number(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidProductionValueError("order_number must be text.")
    normalized = value.strip().upper()
    if re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{0,39}", normalized) is None:
        raise InvalidProductionValueError("order_number must be a canonical identifier.")
    return normalized


@dataclass(frozen=True, slots=True)
class ProductionOrder:
    id: UUID
    company_id: UUID
    order_number: str
    product_id: UUID
    planned_quantity: ProductionQuantity
    planned_start_on: date
    due_on: date
    engineering: ProductionEngineeringSnapshot
    materials: tuple[ProductionMaterialPlan, ...]
    operations: tuple[ProductionOrderOperation, ...]
    created_at: datetime
    created_by: UUID
    status: ProductionOrderStatus = ProductionOrderStatus.DRAFT
    output_lots: tuple[ProductionLotTrace, ...] = ()
    released_at: datetime | None = None
    released_by: UUID | None = None
    started_at: datetime | None = None
    started_by: UUID | None = None
    completed_at: datetime | None = None
    completed_by: UUID | None = None
    cancelled_at: datetime | None = None
    cancelled_by: UUID | None = None
    cancellation_reason: str | None = None
    record_version: int = 1

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        order_number: str,
        product_id: UUID,
        planned_quantity: ProductionQuantity,
        planned_start_on: date,
        due_on: date,
        bom: BillOfMaterials,
        routing: ProductionRouting,
        material_requirements: tuple[MaterialRequirement, ...],
        engineering_approved_at: datetime,
        engineering_approved_by: UUID,
        created_at: datetime,
        created_by: UUID,
        order_id: UUID | None = None,
    ) -> ProductionOrder:
        engineering = ProductionEngineeringSnapshot.capture(
            bom=bom,
            routing=routing,
            approved_at=engineering_approved_at,
            approved_by=engineering_approved_by,
            planned_start_on=planned_start_on,
        )
        if company_id != engineering.company_id or product_id != engineering.product_id:
            raise ProductionScopeError(
                "production order, BOM and routing must own the same tenant product."
            )
        if planned_quantity.unit is not engineering.bom_output_quantity.unit:
            raise UnitOfMeasureMismatchError(
                "planned production unit must match the approved BOM output unit."
            )
        if not isinstance(material_requirements, tuple) or not material_requirements:
            raise InvalidProductionValueError(
                "material_requirements must be a non-empty tuple."
            )
        if any(
            not isinstance(requirement, MaterialRequirement)
            for requirement in material_requirements
        ):
            raise InvalidProductionValueError(
                "material_requirements must contain MaterialRequirement values."
            )
        return cls(
            id=order_id or uuid4(),
            company_id=company_id,
            order_number=order_number,
            product_id=product_id,
            planned_quantity=planned_quantity,
            planned_start_on=planned_start_on,
            due_on=due_on,
            engineering=engineering,
            materials=tuple(
                ProductionMaterialPlan(
                    product_id=requirement.product_id,
                    planned_quantity=requirement.quantity,
                )
                for requirement in material_requirements
            ),
            operations=tuple(
                ProductionOrderOperation.from_routing(operation)
                for operation in routing.operations
            ),
            created_at=created_at,
            created_by=created_by,
        )

    def __post_init__(self) -> None:
        require_uuid(self.id, "id")
        require_uuid(self.company_id, "company_id")
        require_uuid(self.product_id, "product_id")
        require_uuid(self.created_by, "created_by")
        object.__setattr__(self, "order_number", _order_number(self.order_number))
        if not isinstance(self.planned_quantity, ProductionQuantity):
            raise InvalidProductionValueError(
                "planned_quantity must be a ProductionQuantity."
            )
        _date(self.planned_start_on, "planned_start_on")
        _date(self.due_on, "due_on")
        if self.due_on < self.planned_start_on:
            raise InvalidProductionValueError("due_on cannot precede planned_start_on.")
        if not isinstance(self.engineering, ProductionEngineeringSnapshot):
            raise InvalidProductionValueError(
                "engineering must be a ProductionEngineeringSnapshot."
            )
        if (
            self.engineering.company_id != self.company_id
            or self.engineering.product_id != self.product_id
        ):
            raise ProductionScopeError("engineering snapshot is outside the order scope.")
        if self.planned_quantity.unit is not self.engineering.bom_output_quantity.unit:
            raise UnitOfMeasureMismatchError(
                "order and engineering output units must match."
            )
        self._validate_materials()
        self._validate_operations()
        _aware_datetime(self.created_at, "created_at")
        if not isinstance(self.status, ProductionOrderStatus):
            raise InvalidProductionValueError("status must be a ProductionOrderStatus.")
        if not isinstance(self.output_lots, tuple) or any(
            not isinstance(item, ProductionLotTrace) for item in self.output_lots
        ):
            raise InvalidProductionValueError(
                "output_lots must be a tuple of ProductionLotTrace values."
            )
        if type(self.record_version) is not int or self.record_version < 1:
            raise InvalidProductionValueError("record_version must be a positive integer.")
        self._validate_lifecycle_evidence()

    @property
    def actual_output_amount(self) -> Decimal:
        return sum(
            (item.quantity.amount for item in self.output_lots),
            start=Decimal("0"),
        )

    @property
    def output_variance(self) -> Decimal:
        return self.actual_output_amount - self.planned_quantity.amount

    def reschedule(
        self,
        *,
        planned_start_on: date,
        due_on: date,
    ) -> ProductionOrder:
        self._require_status(ProductionOrderStatus.DRAFT)
        _date(planned_start_on, "planned_start_on")
        _date(due_on, "due_on")
        if due_on < planned_start_on:
            raise InvalidProductionValueError("due_on cannot precede planned_start_on.")
        if not self.engineering.is_effective_on(planned_start_on):
            raise EngineeringUnavailableError(
                "approved engineering is not effective on the new start date."
            )
        return replace(
            self,
            planned_start_on=planned_start_on,
            due_on=due_on,
            record_version=self.record_version + 1,
        )

    def release(
        self,
        *,
        bom: BillOfMaterials,
        routing: ProductionRouting,
        actor_id: UUID,
        occurred_at: datetime,
    ) -> ProductionOrder:
        self._require_status(ProductionOrderStatus.DRAFT)
        self.engineering.require_available(
            bom=bom,
            routing=routing,
            on_date=self.planned_start_on,
        )
        timestamp = self._transition_time(occurred_at)
        return replace(
            self,
            status=ProductionOrderStatus.RELEASED,
            released_at=timestamp,
            released_by=require_uuid(actor_id, "actor_id"),
            record_version=self.record_version + 1,
        )

    def start_operation(
        self,
        sequence: int,
        *,
        work_center: WorkCenter,
        actor_id: UUID,
        occurred_at: datetime,
    ) -> ProductionOrder:
        if self.status not in {
            ProductionOrderStatus.RELEASED,
            ProductionOrderStatus.IN_PROGRESS,
        }:
            raise InvalidProductionOrderStateError(
                "only released or in-progress orders can start an operation."
            )
        operation_index = self._operation_index(sequence)
        if any(
            operation.status is not ProductionOperationStatus.COMPLETED
            for operation in self.operations[:operation_index]
        ):
            raise RoutingConsistencyError(
                "routing operations must start in their approved sequence."
            )
        if any(
            operation.status is ProductionOperationStatus.IN_PROGRESS
            for operation in self.operations
        ):
            raise RoutingConsistencyError("another routing operation is already in progress.")
        timestamp = self._transition_time(occurred_at)
        started = self.operations[operation_index].start(
            work_center=work_center,
            actor_id=actor_id,
            occurred_at=timestamp,
        )
        operations = self._replace_operation(operation_index, started)
        return replace(
            self,
            status=ProductionOrderStatus.IN_PROGRESS,
            operations=operations,
            started_at=self.started_at or timestamp,
            started_by=self.started_by or require_uuid(actor_id, "actor_id"),
            record_version=self.record_version + 1,
        )

    def complete_operation(
        self,
        sequence: int,
        *,
        actor_id: UUID,
        occurred_at: datetime,
    ) -> ProductionOrder:
        self._require_status(ProductionOrderStatus.IN_PROGRESS)
        operation_index = self._operation_index(sequence)
        completed = self.operations[operation_index].complete(
            actor_id=actor_id,
            occurred_at=self._transition_time(occurred_at),
        )
        return replace(
            self,
            operations=self._replace_operation(operation_index, completed),
            record_version=self.record_version + 1,
        )

    def record_consumption(self, trace: ProductionLotTrace) -> ProductionOrder:
        self._require_status(ProductionOrderStatus.IN_PROGRESS)
        if not isinstance(trace, ProductionLotTrace):
            raise InvalidProductionValueError("trace must be a ProductionLotTrace.")
        index = next(
            (
                position
                for position, material in enumerate(self.materials)
                if material.product_id == trace.product_id
            ),
            None,
        )
        if index is None:
            raise LotTraceabilityError("lot product is not planned for this order.")
        consumed = self.materials[index].consume(trace)
        materials = tuple(
            consumed if position == index else material
            for position, material in enumerate(self.materials)
        )
        return replace(
            self,
            materials=materials,
            record_version=self.record_version + 1,
        )

    def complete(
        self,
        *,
        output_lots: tuple[ProductionLotTrace, ...],
        actor_id: UUID,
        occurred_at: datetime,
    ) -> ProductionOrder:
        self._require_status(ProductionOrderStatus.IN_PROGRESS)
        if any(
            operation.status is not ProductionOperationStatus.COMPLETED
            for operation in self.operations
        ):
            raise RoutingConsistencyError(
                "all approved routing operations must be completed."
            )
        if any(material.actual_amount <= 0 for material in self.materials):
            raise LotTraceabilityError(
                "every planned material requires lot consumption evidence."
            )
        self._validate_output_lots(output_lots)
        timestamp = self._transition_time(occurred_at)
        return replace(
            self,
            status=ProductionOrderStatus.COMPLETED,
            output_lots=output_lots,
            completed_at=timestamp,
            completed_by=require_uuid(actor_id, "actor_id"),
            record_version=self.record_version + 1,
        )

    def cancel(
        self,
        *,
        reason: str,
        actor_id: UUID,
        occurred_at: datetime,
    ) -> ProductionOrder:
        if self.status not in {
            ProductionOrderStatus.DRAFT,
            ProductionOrderStatus.RELEASED,
        }:
            raise InvalidProductionOrderStateError(
                "only draft or released production orders can be cancelled."
            )
        if not isinstance(reason, str):
            raise InvalidProductionValueError("cancellation reason must be text.")
        normalized_reason = " ".join(reason.split())
        if not 3 <= len(normalized_reason) <= 500:
            raise InvalidProductionValueError(
                "cancellation reason must contain between 3 and 500 characters."
            )
        timestamp = self._transition_time(occurred_at)
        return replace(
            self,
            status=ProductionOrderStatus.CANCELLED,
            cancelled_at=timestamp,
            cancelled_by=require_uuid(actor_id, "actor_id"),
            cancellation_reason=normalized_reason,
            record_version=self.record_version + 1,
        )

    def _validate_materials(self) -> None:
        if not isinstance(self.materials, tuple) or not self.materials:
            raise InvalidProductionValueError("materials must be a non-empty tuple.")
        if any(not isinstance(item, ProductionMaterialPlan) for item in self.materials):
            raise InvalidProductionValueError(
                "materials must contain ProductionMaterialPlan values."
            )
        product_ids = tuple(item.product_id for item in self.materials)
        if len(product_ids) != len(set(product_ids)):
            raise InvalidProductionValueError("planned material products must be unique.")
        if self.product_id in product_ids:
            raise InvalidProductionValueError(
                "production output cannot also be a planned material."
            )

    def _validate_operations(self) -> None:
        if not isinstance(self.operations, tuple) or not self.operations:
            raise InvalidProductionValueError("operations must be a non-empty tuple.")
        if any(
            not isinstance(operation, ProductionOrderOperation)
            for operation in self.operations
        ):
            raise InvalidProductionValueError(
                "operations must contain ProductionOrderOperation values."
            )
        sequences = tuple(operation.sequence for operation in self.operations)
        if len(sequences) != len(set(sequences)) or sequences != tuple(sorted(sequences)):
            raise RoutingConsistencyError(
                "production operations must be unique and ordered."
            )
        if any(
            operation.work_center.company_id != self.company_id
            for operation in self.operations
        ):
            raise ProductionScopeError("operation belongs to another company.")

    def _validate_lifecycle_evidence(self) -> None:
        if self.status is ProductionOrderStatus.DRAFT:
            if any(
                value is not None
                for value in (
                    self.released_at,
                    self.released_by,
                    self.started_at,
                    self.started_by,
                    self.completed_at,
                    self.completed_by,
                    self.cancelled_at,
                    self.cancelled_by,
                    self.cancellation_reason,
                )
            ):
                raise InvalidProductionOrderStateError(
                    "draft orders cannot contain lifecycle evidence."
                )
            if any(
                operation.status is not ProductionOperationStatus.PENDING
                for operation in self.operations
            ):
                raise RoutingConsistencyError("draft operations must remain pending.")
            if self.output_lots:
                raise LotTraceabilityError("draft orders cannot contain output lots.")
            return
        if self.status is ProductionOrderStatus.CANCELLED:
            if (
                self.cancelled_at is None
                or self.cancelled_by is None
                or self.cancellation_reason is None
            ):
                raise InvalidProductionOrderStateError(
                    "cancelled orders require cancellation evidence."
                )
            _aware_datetime(self.cancelled_at, "cancelled_at")
            require_uuid(self.cancelled_by, "cancelled_by")
            if self.output_lots:
                raise LotTraceabilityError("cancelled orders cannot contain output lots.")
            return
        if self.released_at is None or self.released_by is None:
            raise InvalidProductionOrderStateError(
                "released lifecycle states require release evidence."
            )
        _aware_datetime(self.released_at, "released_at")
        require_uuid(self.released_by, "released_by")
        if self.status is ProductionOrderStatus.RELEASED:
            if any(
                operation.status is not ProductionOperationStatus.PENDING
                for operation in self.operations
            ):
                raise RoutingConsistencyError("released operations must remain pending.")
            if self.output_lots:
                raise LotTraceabilityError("released orders cannot contain output lots.")
            return
        if self.started_at is None or self.started_by is None:
            raise InvalidProductionOrderStateError(
                "in-progress lifecycle states require start evidence."
            )
        _aware_datetime(self.started_at, "started_at")
        require_uuid(self.started_by, "started_by")
        if self.status is ProductionOrderStatus.IN_PROGRESS:
            if not any(
                operation.status is not ProductionOperationStatus.PENDING
                for operation in self.operations
            ):
                raise RoutingConsistencyError(
                    "in-progress orders require routing execution evidence."
                )
            if self.output_lots:
                raise LotTraceabilityError(
                    "in-progress orders cannot contain finished output lots."
                )
            return
        if self.completed_at is None or self.completed_by is None:
            raise InvalidProductionOrderStateError(
                "completed orders require completion evidence."
            )
        _aware_datetime(self.completed_at, "completed_at")
        require_uuid(self.completed_by, "completed_by")
        if any(
            operation.status is not ProductionOperationStatus.COMPLETED
            for operation in self.operations
        ):
            raise RoutingConsistencyError("completed orders require a completed routing.")
        self._validate_output_lots(self.output_lots)

    def _validate_output_lots(
        self,
        output_lots: tuple[ProductionLotTrace, ...],
    ) -> None:
        if not isinstance(output_lots, tuple) or not output_lots:
            raise LotTraceabilityError("completion requires output lot evidence.")
        if any(not isinstance(item, ProductionLotTrace) for item in output_lots):
            raise LotTraceabilityError(
                "output_lots must contain ProductionLotTrace values."
            )
        if any(item.product_id != self.product_id for item in output_lots):
            raise LotTraceabilityError("output lot must reference the produced product.")
        if any(item.quantity.unit is not self.planned_quantity.unit for item in output_lots):
            raise UnitOfMeasureMismatchError(
                "output lots must use the planned production unit."
            )
        lot_ids = tuple(item.lot_id for item in output_lots)
        if len(lot_ids) != len(set(lot_ids)):
            raise LotTraceabilityError("output lot references must be unique.")
        actual_amount = sum(
            (item.quantity.amount for item in output_lots),
            start=Decimal("0"),
        )
        if actual_amount > self.planned_quantity.amount:
            raise ProductionQuantityExceededError(
                "actual output cannot exceed the planned order quantity."
            )

    def _operation_index(self, sequence: int) -> int:
        if type(sequence) is not int:
            raise InvalidProductionValueError("operation sequence must be an integer.")
        index = next(
            (
                position
                for position, operation in enumerate(self.operations)
                if operation.sequence == sequence
            ),
            None,
        )
        if index is None:
            raise RoutingConsistencyError("operation is outside the approved routing.")
        return index

    def _replace_operation(
        self,
        index: int,
        replacement: ProductionOrderOperation,
    ) -> tuple[ProductionOrderOperation, ...]:
        return tuple(
            replacement if position == index else operation
            for position, operation in enumerate(self.operations)
        )

    def _transition_time(self, occurred_at: datetime) -> datetime:
        timestamp = _aware_datetime(occurred_at, "occurred_at")
        if timestamp < self.created_at:
            raise InvalidProductionValueError(
                "lifecycle timestamps cannot precede order creation."
            )
        return timestamp

    def _require_status(self, expected: ProductionOrderStatus) -> None:
        if self.status is not expected:
            raise InvalidProductionOrderStateError(
                f"production order must be {expected.value}."
            )


__all__ = ["ProductionOrder"]

