"""HTTP composition for the read-only Production cockpit."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.production.api.schemas import (
    ProductionAlertResponse,
    ProductionCockpitResponse,
    ProductionOrderCockpitResponse,
    WorkCenterLoadResponse,
)
from erp.modules.production.application import ProductionCockpitService
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/production", tags=["production"])


def get_production_cockpit(request: Request) -> ProductionCockpitService:
    service = getattr(request.app.state, "production_cockpit", None)
    if not isinstance(service, ProductionCockpitService):
        raise ApplicationError(
            code="PRODUCTION_COCKPIT_UNAVAILABLE",
            message="Production cockpit service unavailable.",
            status_code=503,
        )
    return service


@router.get("/cockpit", response_model=ProductionCockpitResponse)
async def get_cockpit_snapshot(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[ProductionCockpitService, Depends(get_production_cockpit)],
    company_id: UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ProductionCockpitResponse:
    snapshot = await service.snapshot(context, company_id, limit=limit)
    response.headers["Cache-Control"] = "no-store"
    return ProductionCockpitResponse(
        company_id=snapshot.company_id,
        generated_at=snapshot.generated_at,
        standard_shift_minutes=snapshot.standard_shift_minutes,
        orders=[
            ProductionOrderCockpitResponse(
                id=value.id,
                order_number=value.order_number,
                product_id=value.product_id,
                status=value.status,
                planned_quantity=value.planned_quantity,
                planned_uom=value.planned_uom,
                good_quantity=value.good_quantity,
                scrap_quantity=value.scrap_quantity,
                progress_percent=value.progress_percent,
                completed_operations=value.completed_operations,
                total_operations=value.total_operations,
                current_operation=value.current_operation,
                current_work_center=value.current_work_center,
                planned_start_on=value.planned_start_on,
                due_on=value.due_on,
                synchronization_pending=value.synchronization_pending,
                last_synchronization_at=value.last_synchronization_at,
            )
            for value in snapshot.orders
        ],
        work_centers=[
            WorkCenterLoadResponse(
                code=value.code,
                capabilities=list(value.capabilities),
                planned_minutes=value.planned_minutes,
                capacity_minutes=value.capacity_minutes,
                load_percent=value.load_percent,
                active_operations=value.active_operations,
                state=value.state,
            )
            for value in snapshot.work_centers
        ],
        alerts=[
            ProductionAlertResponse(
                severity=value.severity,
                alert_type=value.alert_type,
                title=value.title,
                message=value.message,
                production_order_id=value.production_order_id,
                work_center_code=value.work_center_code,
            )
            for value in snapshot.alerts
        ],
        pending_synchronizations=snapshot.pending_synchronizations,
    )


__all__ = ["get_production_cockpit", "router"]
