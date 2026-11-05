"""Immutable snapshots and execution values for production orders."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from erp.modules.production.domain.bom import BillOfMaterials
from erp.modules.production.domain.exceptions import (
    EngineeringUnavailableError,
    InvalidProductionOrderStateError,
    InvalidProductionValueError,
    LotTraceabilityError,
    ProductionQuantityExceededError,
    RoutingConsistencyError,
    UnitOfMeasureMismatchError,
)
from erp.modules.production.domain.routing import (
    ProductionRouting,
    RoutingOperation,
    WorkCenter,
    WorkCenterConstraint,
)
from erp.modules.production.domain.values import (
    EngineeringVersion,
    ProductionQuantity,
    require_uuid,
)


def _aware_datetime(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidProductionValueError(f"{field} must be a timezone-aware datetime.")
    return value


def _date(value: date, field: str) -> date:
    if type(value) is not date:
        raise InvalidProductionValueError(f"{field} must be a date.")
    return value


def _effective(version: EngineeringVersion, on_date: date) -> bool:
    return version.effective_from <= on_date and (
        version.effective_until is None or on_date <= version.effective_until
    )


class ProductionOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProductionOperationStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class ProductionEngineeringSnapshot:
    company_id: UUID
    product_id: UUID
    bom_version: EngineeringVersion
    bom_record_version: int
    routing_version: EngineeringVersion
    routing_record_version: int
    bom_output_quantity: ProductionQuantity
    approved_at: datetime
    approved_by: UUID

    @classmethod
    def capture(
        cls,
        *,
        bom: BillOfMaterials,
        routing: ProductionRouting,
        approved_at: datetime,
        approved_by: UUID,
        planned_start_on: date,
    ) -> ProductionEngineeringSnapshot:
        if not isinstance(bom, BillOfMaterials):
            raise InvalidProductionValueError("bom must be a BillOfMaterials.")
        if not isinstance(routing, ProductionRouting):
            raise InvalidProductionValueError("routing must be a ProductionRouting.")
        _date(planned_start_on, "planned_start_on")
        if bom.company_id != routing.company_id or bom.product_id != routing.product_id:
            raise RoutingConsistencyError("BOM and routing must own the same tenant product.")
        if not _effective(bom.version, planned_start_on) or not _effective(
            routing.version, planned_start_on
        ):
            raise EngineeringUnavailableError(
                "BOM and routing must be effective on the planned production date."
            )
        return cls(
            company_id=bom.company_id,
            product_id=bom.product_id,
            bom_version=bom.version,
            bom_record_version=bom.record_version,
            routing_version=routing.version,
            routing_record_version=routing.record_version,
            bom_output_quantity=bom.output_quantity,
            approved_at=approved_at,
            approved_by=approved_by,
        )

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        require_uuid(self.product_id, "product_id")
        require_uuid(self.approved_by, "approved_by")
        _aware_datetime(self.approved_at, "approved_at")
        if not isinstance(self.bom_version, EngineeringVersion) or not isinstance(
            self.routing_version, EngineeringVersion
        ):
            raise InvalidProductionValueError(
                "engineering versions must be EngineeringVersion values."
            )
        if (
            type(self.bom_record_version) is not int
            or self.bom_record_version < 1
            or type(self.routing_record_version) is not int
            or self.routing_record_version < 1
        ):
            raise InvalidProductionValueError(
                "engineering record versions must be positive integers."
            )
        if not isinstance(self.bom_output_quantity, ProductionQuantity):
            raise InvalidProductionValueError(
                "bom_output_quantity must be a ProductionQuantity."
            )

    def require_available(
        self,
        *,
        bom: BillOfMaterials,
        routing: ProductionRouting,
        on_date: date,
    ) -> None:
        _date(on_date, "on_date")
        matches = (
            isinstance(bom, BillOfMaterials)
            and isinstance(routing, ProductionRouting)
            and bom.company_id == self.company_id
            and routing.company_id == self.company_id
            and bom.product_id == self.product_id
            and routing.product_id == self.product_id
            and bom.version == self.bom_version
            and routing.version == self.routing_version
            and bom.record_version == self.bom_record_version
            and routing.record_version == self.routing_record_version
            and _effective(bom.version, on_date)
            and _effective(routing.version, on_date)
        )
        if not matches:
            raise EngineeringUnavailableError(
                "The approved BOM or routing is unavailable or changed."
            )

    def is_effective_on(self, on_date: date) -> bool:
        _date(on_date, "on_date")
        return _effective(self.bom_version, on_date) and _effective(
            self.routing_version, on_date
        )


@dataclass(frozen=True, slots=True)
class ProductionLotTrace:
    lot_id: UUID
    product_id: UUID
    quantity: ProductionQuantity

    def __post_init__(self) -> None:
        require_uuid(self.lot_id, "lot_id")
        require_uuid(self.product_id, "product_id")
        if not isinstance(self.quantity, ProductionQuantity):
            raise InvalidProductionValueError("quantity must be a ProductionQuantity.")


@dataclass(frozen=True, slots=True)
class ProductionMaterialPlan:
    product_id: UUID
    planned_quantity: ProductionQuantity
    consumptions: tuple[ProductionLotTrace, ...] = ()

    def __post_init__(self) -> None:
        require_uuid(self.product_id, "product_id")
        if not isinstance(self.planned_quantity, ProductionQuantity):
            raise InvalidProductionValueError(
                "planned_quantity must be a ProductionQuantity."
            )
        if not isinstance(self.consumptions, tuple) or any(
            not isinstance(item, ProductionLotTrace) for item in self.consumptions
        ):
            raise InvalidProductionValueError(
                "consumptions must be a tuple of ProductionLotTrace values."
            )
        if any(item.product_id != self.product_id for item in self.consumptions):
            raise LotTraceabilityError("material lots must reference the planned product.")
        if any(
            item.quantity.unit is not self.planned_quantity.unit
            for item in self.consumptions
        ):
            raise UnitOfMeasureMismatchError(
                "material lots must use the planned unit of measure."
            )
        lot_ids = tuple(item.lot_id for item in self.consumptions)
        if len(lot_ids) != len(set(lot_ids)):
            raise LotTraceabilityError("material lot references must be unique.")
        if self.actual_amount > self.planned_quantity.amount:
            raise ProductionQuantityExceededError(
                "material consumption cannot exceed the planned gross requirement."
            )

    @property
    def actual_amount(self) -> Decimal:
        return sum(
            (item.quantity.amount for item in self.consumptions),
            start=Decimal("0"),
        )

    def consume(self, trace: ProductionLotTrace) -> ProductionMaterialPlan:
        if not isinstance(trace, ProductionLotTrace):
            raise InvalidProductionValueError("trace must be a ProductionLotTrace.")
        if trace.product_id != self.product_id:
            raise LotTraceabilityError("lot product does not match the material plan.")
        if trace.quantity.unit is not self.planned_quantity.unit:
            raise UnitOfMeasureMismatchError(
                "consumption unit must match the material plan."
            )
        existing = next(
            (item for item in self.consumptions if item.lot_id == trace.lot_id),
            None,
        )
        if existing is None:
            consumptions = (*self.consumptions, trace)
        else:
            combined = ProductionLotTrace(
                lot_id=trace.lot_id,
                product_id=trace.product_id,
                quantity=ProductionQuantity(
                    existing.quantity.amount + trace.quantity.amount,
                    trace.quantity.unit,
                ),
            )
            consumptions = tuple(
                combined if item.lot_id == trace.lot_id else item
                for item in self.consumptions
            )
        return replace(self, consumptions=consumptions)


@dataclass(frozen=True, slots=True)
class ProductionOrderOperation:
    sequence: int
    name: str
    work_center: WorkCenterConstraint
    status: ProductionOperationStatus = ProductionOperationStatus.PENDING
    assigned_work_center: WorkCenter | None = None
    started_at: datetime | None = None
    started_by: UUID | None = None
    completed_at: datetime | None = None
    completed_by: UUID | None = None

    @classmethod
    def from_routing(cls, operation: RoutingOperation) -> ProductionOrderOperation:
        if not isinstance(operation, RoutingOperation):
            raise InvalidProductionValueError("operation must be a RoutingOperation.")
        return cls(operation.sequence, operation.name, operation.work_center)

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise InvalidProductionValueError("operation sequence must be positive.")
        if not isinstance(self.name, str) or not self.name.strip():
            raise InvalidProductionValueError("operation name must be non-empty text.")
        if not isinstance(self.work_center, WorkCenterConstraint):
            raise InvalidProductionValueError(
                "work_center must be a WorkCenterConstraint."
            )
        if not isinstance(self.status, ProductionOperationStatus):
            raise InvalidProductionValueError(
                "status must be a ProductionOperationStatus."
            )
        if self.status is ProductionOperationStatus.PENDING:
            if any(
                value is not None
                for value in (
                    self.assigned_work_center,
                    self.started_at,
                    self.started_by,
                    self.completed_at,
                    self.completed_by,
                )
            ):
                raise RoutingConsistencyError(
                    "pending operations cannot contain execution evidence."
                )
            return
        if self.assigned_work_center is None or self.started_at is None or self.started_by is None:
            raise RoutingConsistencyError(
                "started operations require work center, timestamp and actor."
            )
        if not self.work_center.accepts(self.assigned_work_center):
            raise RoutingConsistencyError(
                "assigned work center does not satisfy the approved routing."
            )
        _aware_datetime(self.started_at, "started_at")
        require_uuid(self.started_by, "started_by")
        if self.status is ProductionOperationStatus.IN_PROGRESS:
            if self.completed_at is not None or self.completed_by is not None:
                raise RoutingConsistencyError(
                    "in-progress operations cannot contain completion evidence."
                )
            return
        if self.completed_at is None or self.completed_by is None:
            raise RoutingConsistencyError(
                "completed operations require completion timestamp and actor."
            )
        _aware_datetime(self.completed_at, "completed_at")
        require_uuid(self.completed_by, "completed_by")
        if self.completed_at < self.started_at:
            raise RoutingConsistencyError("operation completion cannot precede its start.")

    def start(
        self,
        *,
        work_center: WorkCenter,
        actor_id: UUID,
        occurred_at: datetime,
    ) -> ProductionOrderOperation:
        if self.status is not ProductionOperationStatus.PENDING:
            raise InvalidProductionOrderStateError("operation is not pending.")
        self.work_center.accepts(work_center)
        return replace(
            self,
            status=ProductionOperationStatus.IN_PROGRESS,
            assigned_work_center=work_center,
            started_at=_aware_datetime(occurred_at, "occurred_at"),
            started_by=require_uuid(actor_id, "actor_id"),
        )

    def complete(
        self,
        *,
        actor_id: UUID,
        occurred_at: datetime,
    ) -> ProductionOrderOperation:
        if self.status is not ProductionOperationStatus.IN_PROGRESS:
            raise InvalidProductionOrderStateError("operation is not in progress.")
        return replace(
            self,
            status=ProductionOperationStatus.COMPLETED,
            completed_at=_aware_datetime(occurred_at, "occurred_at"),
            completed_by=require_uuid(actor_id, "actor_id"),
        )


__all__ = [
    "ProductionEngineeringSnapshot",
    "ProductionLotTrace",
    "ProductionMaterialPlan",
    "ProductionOperationStatus",
    "ProductionOrderOperation",
    "ProductionOrderStatus",
]

