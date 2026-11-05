"""Immutable planning inputs and outputs for deterministic MRP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from uuid import UUID

from erp.modules.production.domain.exceptions import (
    InvalidProductionValueError,
    ProductionScopeError,
    UnitOfMeasureMismatchError,
)
from erp.modules.production.domain.values import (
    ProductionQuantity,
    UnitOfMeasure,
    normalized_decimal,
    require_uuid,
)


def _date(value: date, field: str) -> date:
    if type(value) is not date:
        raise InvalidProductionValueError(f"{field} must be a date.")
    return value


def _nonnegative(value: Decimal, field: str) -> Decimal:
    normalized = normalized_decimal(value, field)
    if normalized < 0:
        raise InvalidProductionValueError(f"{field} cannot be negative.")
    return normalized


class MRPDemandSource(StrEnum):
    SALES_ORDER = "SALES_ORDER"
    FORECAST = "FORECAST"


class MRPSupplyMode(StrEnum):
    MAKE = "MAKE"
    BUY = "BUY"


class MRPScheduledReceiptType(StrEnum):
    PRODUCTION_ORDER = "PRODUCTION_ORDER"
    PURCHASE_ORDER = "PURCHASE_ORDER"


class MRPPlannedOrderType(StrEnum):
    MANUFACTURE = "MANUFACTURE"
    PURCHASE = "PURCHASE"


class MRPAlertKind(StrEnum):
    LEAD_TIME_CONSTRAINT = "LEAD_TIME_CONSTRAINT"


@dataclass(frozen=True, slots=True)
class MRPDemand:
    company_id: UUID
    source_id: UUID
    source: MRPDemandSource
    product_id: UUID
    quantity: ProductionQuantity
    required_on: date

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        require_uuid(self.source_id, "source_id")
        require_uuid(self.product_id, "product_id")
        if not isinstance(self.source, MRPDemandSource):
            raise InvalidProductionValueError("source must be an MRPDemandSource.")
        if not isinstance(self.quantity, ProductionQuantity):
            raise InvalidProductionValueError(
                "quantity must be a ProductionQuantity."
            )
        _date(self.required_on, "required_on")


@dataclass(frozen=True, slots=True)
class MRPInventoryPosition:
    company_id: UUID
    product_id: UUID
    unit: UnitOfMeasure
    on_hand: Decimal = Decimal("0")
    allocated: Decimal = Decimal("0")
    safety_stock: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        require_uuid(self.product_id, "product_id")
        if not isinstance(self.unit, UnitOfMeasure):
            raise InvalidProductionValueError("unit must be a UnitOfMeasure.")
        object.__setattr__(self, "on_hand", _nonnegative(self.on_hand, "on_hand"))
        object.__setattr__(
            self,
            "allocated",
            _nonnegative(self.allocated, "allocated"),
        )
        object.__setattr__(
            self,
            "safety_stock",
            _nonnegative(self.safety_stock, "safety_stock"),
        )

    @property
    def net_available(self) -> Decimal:
        return self.on_hand - self.allocated - self.safety_stock


@dataclass(frozen=True, slots=True)
class MRPScheduledReceipt:
    company_id: UUID
    receipt_id: UUID
    receipt_type: MRPScheduledReceiptType
    product_id: UUID
    quantity: ProductionQuantity
    available_on: date

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        require_uuid(self.receipt_id, "receipt_id")
        require_uuid(self.product_id, "product_id")
        if not isinstance(self.receipt_type, MRPScheduledReceiptType):
            raise InvalidProductionValueError(
                "receipt_type must be an MRPScheduledReceiptType."
            )
        if not isinstance(self.quantity, ProductionQuantity):
            raise InvalidProductionValueError(
                "quantity must be a ProductionQuantity."
            )
        _date(self.available_on, "available_on")


@dataclass(frozen=True, slots=True)
class MRPPlanningPolicy:
    company_id: UUID
    product_id: UUID
    supply_mode: MRPSupplyMode
    minimum_lot: ProductionQuantity
    lead_time_days: int
    lot_multiple: ProductionQuantity | None = None

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        require_uuid(self.product_id, "product_id")
        if not isinstance(self.supply_mode, MRPSupplyMode):
            raise InvalidProductionValueError(
                "supply_mode must be an MRPSupplyMode."
            )
        if not isinstance(self.minimum_lot, ProductionQuantity):
            raise InvalidProductionValueError(
                "minimum_lot must be a ProductionQuantity."
            )
        if type(self.lead_time_days) is not int or self.lead_time_days < 0:
            raise InvalidProductionValueError(
                "lead_time_days must be a non-negative integer."
            )
        if self.lot_multiple is not None:
            if not isinstance(self.lot_multiple, ProductionQuantity):
                raise InvalidProductionValueError(
                    "lot_multiple must be a ProductionQuantity."
                )
            if self.lot_multiple.unit is not self.minimum_lot.unit:
                raise UnitOfMeasureMismatchError(
                    "minimum lot and lot multiple must use the same unit."
                )

    def size(self, net_requirement: Decimal, unit: UnitOfMeasure) -> ProductionQuantity:
        required = normalized_decimal(net_requirement, "net_requirement")
        if required <= 0:
            raise InvalidProductionValueError("net_requirement must be positive.")
        if unit is not self.minimum_lot.unit:
            raise UnitOfMeasureMismatchError(
                "requirement unit must match the planning policy."
            )
        amount = max(required, self.minimum_lot.amount)
        if self.lot_multiple is not None:
            multiples = (amount / self.lot_multiple.amount).to_integral_value(
                rounding=ROUND_CEILING
            )
            amount = multiples * self.lot_multiple.amount
        return ProductionQuantity(amount, unit)


@dataclass(frozen=True, slots=True)
class MRPNetRequirement:
    company_id: UUID
    product_id: UUID
    required_on: date
    unit: UnitOfMeasure
    gross_amount: Decimal
    available_applied: Decimal
    scheduled_receipts_applied: Decimal
    net_amount: Decimal
    planned_receipt_amount: Decimal
    projected_available: Decimal
    source_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        require_uuid(self.product_id, "product_id")
        _date(self.required_on, "required_on")
        if not isinstance(self.unit, UnitOfMeasure):
            raise InvalidProductionValueError("unit must be a UnitOfMeasure.")
        for field in (
            "gross_amount",
            "available_applied",
            "scheduled_receipts_applied",
            "net_amount",
            "planned_receipt_amount",
            "projected_available",
        ):
            object.__setattr__(self, field, _nonnegative(getattr(self, field), field))
        if not isinstance(self.source_ids, tuple) or not self.source_ids:
            raise InvalidProductionValueError("source_ids must be a non-empty tuple.")
        if any(not isinstance(value, UUID) or value.int == 0 for value in self.source_ids):
            raise InvalidProductionValueError(
                "source_ids must contain non-zero UUID values."
            )
        if len(self.source_ids) != len(set(self.source_ids)):
            raise InvalidProductionValueError("source_ids must be unique.")


@dataclass(frozen=True, slots=True)
class MRPPlannedOrder:
    id: UUID
    company_id: UUID
    order_type: MRPPlannedOrderType
    product_id: UUID
    quantity: ProductionQuantity
    due_on: date
    release_on: date
    source_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        require_uuid(self.id, "id")
        require_uuid(self.company_id, "company_id")
        require_uuid(self.product_id, "product_id")
        if not isinstance(self.order_type, MRPPlannedOrderType):
            raise InvalidProductionValueError(
                "order_type must be an MRPPlannedOrderType."
            )
        if not isinstance(self.quantity, ProductionQuantity):
            raise InvalidProductionValueError(
                "quantity must be a ProductionQuantity."
            )
        _date(self.due_on, "due_on")
        _date(self.release_on, "release_on")
        if self.release_on > self.due_on:
            raise InvalidProductionValueError("release_on cannot follow due_on.")
        if not isinstance(self.source_ids, tuple) or not self.source_ids:
            raise InvalidProductionValueError("source_ids must be a non-empty tuple.")
        if any(not isinstance(value, UUID) or value.int == 0 for value in self.source_ids):
            raise InvalidProductionValueError(
                "source_ids must contain non-zero UUID values."
            )


@dataclass(frozen=True, slots=True)
class MRPPlanningAlert:
    company_id: UUID
    kind: MRPAlertKind
    planned_order_id: UUID
    product_id: UUID
    required_on: date
    calculated_release_on: date
    days_past_due: int

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        require_uuid(self.planned_order_id, "planned_order_id")
        require_uuid(self.product_id, "product_id")
        if not isinstance(self.kind, MRPAlertKind):
            raise InvalidProductionValueError("kind must be an MRPAlertKind.")
        _date(self.required_on, "required_on")
        _date(self.calculated_release_on, "calculated_release_on")
        if type(self.days_past_due) is not int or self.days_past_due < 1:
            raise InvalidProductionValueError("days_past_due must be positive.")


@dataclass(frozen=True, slots=True)
class MRPPlan:
    company_id: UUID
    as_of: date
    demands: tuple[MRPDemand, ...]
    requirements: tuple[MRPNetRequirement, ...]
    planned_orders: tuple[MRPPlannedOrder, ...]
    alerts: tuple[MRPPlanningAlert, ...]

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        _date(self.as_of, "as_of")
        self._validate_collection(self.demands, MRPDemand, "demands")
        self._validate_collection(
            self.requirements,
            MRPNetRequirement,
            "requirements",
        )
        self._validate_collection(
            self.planned_orders,
            MRPPlannedOrder,
            "planned_orders",
        )
        self._validate_collection(self.alerts, MRPPlanningAlert, "alerts")
        if any(
            value.company_id != self.company_id
            for collection in (
                self.demands,
                self.requirements,
                self.planned_orders,
                self.alerts,
            )
            for value in collection
        ):
            raise ProductionScopeError("MRP plan values must belong to one company.")

    @staticmethod
    def _validate_collection(values: tuple[object, ...], kind: type, field: str) -> None:
        if not isinstance(values, tuple) or any(
            not isinstance(value, kind) for value in values
        ):
            raise InvalidProductionValueError(
                f"{field} must be a tuple of {kind.__name__} values."
            )


__all__ = [
    "MRPAlertKind",
    "MRPDemand",
    "MRPDemandSource",
    "MRPInventoryPosition",
    "MRPNetRequirement",
    "MRPPlan",
    "MRPPlannedOrder",
    "MRPPlannedOrderType",
    "MRPPlanningAlert",
    "MRPPlanningPolicy",
    "MRPScheduledReceipt",
    "MRPScheduledReceiptType",
    "MRPSupplyMode",
]
