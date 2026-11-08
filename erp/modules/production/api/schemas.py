"""Production cockpit HTTP response contracts."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ProductionOrderCockpitResponse(BaseModel):
    id: UUID
    order_number: str
    product_id: UUID
    status: str
    planned_quantity: Decimal
    planned_uom: str
    good_quantity: Decimal
    scrap_quantity: Decimal
    progress_percent: Decimal
    completed_operations: int
    total_operations: int
    current_operation: str | None
    current_work_center: str | None
    planned_start_on: date
    due_on: date
    synchronization_pending: bool
    last_synchronization_at: datetime | None


class WorkCenterLoadResponse(BaseModel):
    code: str
    capabilities: list[str]
    planned_minutes: Decimal
    capacity_minutes: Decimal
    load_percent: Decimal
    active_operations: int
    state: str


class ProductionAlertResponse(BaseModel):
    severity: str
    alert_type: str
    title: str
    message: str
    production_order_id: UUID | None
    work_center_code: str | None


class ProductionCockpitResponse(BaseModel):
    company_id: UUID
    generated_at: datetime
    standard_shift_minutes: int
    orders: list[ProductionOrderCockpitResponse]
    work_centers: list[WorkCenterLoadResponse]
    alerts: list[ProductionAlertResponse]
    pending_synchronizations: int


__all__ = [
    "ProductionAlertResponse",
    "ProductionCockpitResponse",
    "ProductionOrderCockpitResponse",
    "WorkCenterLoadResponse",
]
