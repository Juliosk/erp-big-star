"""Transactional conversion of MRP proposals into effective production orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid5

from erp.modules.inventory.contracts import (
    ProductionMaterialRequirementContract,
    ProductionMaterialReservationGateway,
    ReserveProductionMaterialsContract,
)
from erp.modules.production.application.mrp import MRPRun
from erp.modules.production.domain import (
    BillOfMaterials,
    BomExpansionService,
    EngineeringUnavailableError,
    InvalidProductionValueError,
    MRPPlannedOrder,
    MRPPlannedOrderType,
    ProductionConflictError,
    ProductionOrder,
    ProductionRouting,
)


class PlannedOrderStatus(StrEnum):
    PLANNED = "PLANNED"
    CONVERTED = "CONVERTED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class PlannedOrderConversionRecord:
    run: MRPRun
    planned_order: MRPPlannedOrder
    status: PlannedOrderStatus
    version: int
    production_order_id: UUID | None = None
    material_reservation_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run, MRPRun):
            raise InvalidProductionValueError("run must be an MRPRun.")
        if not isinstance(self.planned_order, MRPPlannedOrder):
            raise InvalidProductionValueError(
                "planned_order must be an MRPPlannedOrder."
            )
        if self.planned_order.company_id != self.run.company_id:
            raise InvalidProductionValueError(
                "planned order and run must belong to one company."
            )
        if not isinstance(self.status, PlannedOrderStatus):
            raise InvalidProductionValueError("status must be a PlannedOrderStatus.")
        if type(self.version) is not int or self.version < 1:
            raise InvalidProductionValueError("version must be a positive integer.")
        evidence = (self.production_order_id, self.material_reservation_id)
        if self.status is PlannedOrderStatus.CONVERTED:
            if any(not isinstance(value, UUID) or value.int == 0 for value in evidence):
                raise InvalidProductionValueError(
                    "converted planned orders require production and reservation identifiers."
                )
        elif any(value is not None for value in evidence):
            raise InvalidProductionValueError(
                "unconverted planned orders cannot contain conversion evidence."
            )


@dataclass(frozen=True, slots=True)
class ProductionEngineeringSelection:
    bom: BillOfMaterials
    routing: ProductionRouting

    def __post_init__(self) -> None:
        if not isinstance(self.bom, BillOfMaterials):
            raise InvalidProductionValueError("bom must be a BillOfMaterials.")
        if not isinstance(self.routing, ProductionRouting):
            raise InvalidProductionValueError("routing must be a ProductionRouting.")
        if (
            self.bom.company_id != self.routing.company_id
            or self.bom.product_id != self.routing.product_id
        ):
            raise InvalidProductionValueError(
                "BOM and routing must belong to one tenant product."
            )


class PlannedOrderConversionStore(Protocol):
    async def claim_for_conversion(
        self,
        run_id: UUID,
        planned_order_id: UUID,
    ) -> PlannedOrderConversionRecord | None: ...

    async def mark_converted(
        self,
        *,
        run_id: UUID,
        planned_order_id: UUID,
        production_order_id: UUID,
        material_reservation_id: UUID,
        converted_at: datetime,
        converted_by: UUID,
        expected_version: int,
    ) -> None: ...


class ProductionOrderStore(Protocol):
    async def add(
        self,
        aggregate: ProductionOrder,
        *,
        actor_id: UUID,
    ) -> ProductionOrder: ...

    async def get(self, order_id: UUID) -> ProductionOrder | None: ...


class ProductionEngineeringDirectory(Protocol):
    async def resolve(
        self,
        *,
        company_id: UUID,
        product_id: UUID,
        version_code: str,
        effective_on: date,
    ) -> ProductionEngineeringSelection | None: ...


@dataclass(frozen=True, slots=True)
class ConvertPlannedOrder:
    company_id: UUID
    run_id: UUID
    planned_order_id: UUID
    occurred_at: datetime
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "company_id",
            "run_id",
            "planned_order_id",
            "request_id",
            "correlation_id",
        ):
            value = getattr(self, field)
            if not isinstance(value, UUID) or value.int == 0:
                raise InvalidProductionValueError(f"{field} must be a non-zero UUID.")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise InvalidProductionValueError("occurred_at must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class PlannedOrderConversionResult:
    production_order: ProductionOrder
    material_reservation_id: UUID
    idempotency_replayed: bool = False


class PlannedOrderConversionService:
    """Convert and allocate one manufacture proposal inside a shared transaction."""

    def __init__(
        self,
        *,
        planned_orders: PlannedOrderConversionStore,
        production_orders: ProductionOrderStore,
        engineering: ProductionEngineeringDirectory,
        inventory: ProductionMaterialReservationGateway,
    ) -> None:
        self._planned_orders = planned_orders
        self._production_orders = production_orders
        self._engineering = engineering
        self._inventory = inventory

    async def convert(
        self,
        command: ConvertPlannedOrder,
        *,
        actor_id: UUID,
    ) -> PlannedOrderConversionResult:
        if not isinstance(command, ConvertPlannedOrder):
            raise InvalidProductionValueError(
                "command must be a ConvertPlannedOrder."
            )
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise InvalidProductionValueError("actor_id must be a non-zero UUID.")
        record = await self._planned_orders.claim_for_conversion(
            command.run_id,
            command.planned_order_id,
        )
        if record is None or record.run.company_id != command.company_id:
            raise ProductionConflictError("Planned order was not found in this company.")
        if record.status is PlannedOrderStatus.CONVERTED:
            return await self._replay(record)
        if record.status is not PlannedOrderStatus.PLANNED:
            raise ProductionConflictError("Only PLANNED orders can be converted.")
        planned = record.planned_order
        if planned.order_type is not MRPPlannedOrderType.MANUFACTURE:
            raise ProductionConflictError(
                "Only MANUFACTURE planned orders can become production orders."
            )
        expected_bom = next(
            (bom for bom in record.run.boms if bom.product_id == planned.product_id),
            None,
        )
        if expected_bom is None:
            raise EngineeringUnavailableError(
                "The MRP run has no frozen BOM for the manufactured product."
            )
        selection = await self._engineering.resolve(
            company_id=command.company_id,
            product_id=planned.product_id,
            version_code=expected_bom.version.code,
            effective_on=planned.release_on,
        )
        if selection is None or selection.bom != expected_bom:
            raise EngineeringUnavailableError(
                "The BOM used by MRP is no longer the current validated structure."
            )
        requirements = BomExpansionService(
            command.company_id,
            record.run.boms,
        ).expand(planned.product_id, planned.quantity)
        production_order_id = uuid5(record.run.id, str(planned.id))
        production_order = ProductionOrder.create(
            company_id=command.company_id,
            order_number=_order_number(record.run.id, planned.id),
            product_id=planned.product_id,
            planned_quantity=planned.quantity,
            planned_start_on=planned.release_on,
            due_on=planned.due_on,
            bom=selection.bom,
            routing=selection.routing,
            material_requirements=requirements,
            engineering_approved_at=command.occurred_at,
            engineering_approved_by=actor_id,
            created_at=command.occurred_at,
            created_by=actor_id,
            order_id=production_order_id,
        )
        await self._production_orders.add(production_order, actor_id=actor_id)
        reservation = await self._inventory.reserve_production_materials(
            ReserveProductionMaterialsContract(
                company_id=command.company_id,
                production_order_id=production_order.id,
                requirements=tuple(
                    ProductionMaterialRequirementContract(
                        product_id=value.product_id,
                        quantity=value.quantity.amount,
                    )
                    for value in requirements
                ),
                request_id=command.request_id,
                correlation_id=command.correlation_id,
                source_ip=command.source_ip,
            ),
            actor_id,
        )
        await self._planned_orders.mark_converted(
            run_id=record.run.id,
            planned_order_id=planned.id,
            production_order_id=production_order.id,
            material_reservation_id=reservation.reservation.id,
            converted_at=command.occurred_at,
            converted_by=actor_id,
            expected_version=record.version,
        )
        return PlannedOrderConversionResult(
            production_order=production_order,
            material_reservation_id=reservation.reservation.id,
        )

    async def _replay(
        self,
        record: PlannedOrderConversionRecord,
    ) -> PlannedOrderConversionResult:
        if (
            record.production_order_id is None
            or record.material_reservation_id is None
        ):
            raise ProductionConflictError("Converted planned order has incomplete evidence.")
        production_order = await self._production_orders.get(
            record.production_order_id
        )
        if production_order is None:
            raise ProductionConflictError(
                "Converted planned order references a missing production order."
            )
        return PlannedOrderConversionResult(
            production_order=production_order,
            material_reservation_id=record.material_reservation_id,
            idempotency_replayed=True,
        )


def _order_number(run_id: UUID, planned_order_id: UUID) -> str:
    return f"OP-MRP-{run_id.hex[:8]}-{planned_order_id.hex[:8]}".upper()


__all__ = [
    "ConvertPlannedOrder",
    "PlannedOrderConversionRecord",
    "PlannedOrderConversionResult",
    "PlannedOrderConversionService",
    "PlannedOrderConversionStore",
    "PlannedOrderStatus",
    "ProductionEngineeringDirectory",
    "ProductionEngineeringSelection",
    "ProductionOrderStore",
]
