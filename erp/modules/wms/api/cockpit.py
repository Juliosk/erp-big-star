"""HTTP endpoint for the read-only WMS operations cockpit."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.wms.api.schemas import (
    WmsCockpitResponse,
    WmsCockpitWaveResponse,
    WmsDispatchQueueResponse,
    WmsZoneOccupancyResponse,
)
from erp.modules.wms.application import WmsCockpitService
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/wms", tags=["wms"])


def get_wms_cockpit(request: Request) -> WmsCockpitService:
    service = getattr(request.app.state, "wms_operations_cockpit", None)
    if not isinstance(service, WmsCockpitService):
        raise ApplicationError(
            code="WMS_COCKPIT_UNAVAILABLE",
            message="WMS cockpit service unavailable.",
            status_code=503,
        )
    return service


@router.get("/cockpit", response_model=WmsCockpitResponse)
async def get_cockpit_snapshot(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[WmsCockpitService, Depends(get_wms_cockpit)],
    company_id: UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> WmsCockpitResponse:
    snapshot = await service.snapshot(context, company_id, limit=limit)
    response.headers["Cache-Control"] = "no-store"
    return WmsCockpitResponse(
        company_id=snapshot.company_id,
        generated_at=snapshot.generated_at,
        total_bins=snapshot.total_bins,
        blocked_bins=snapshot.blocked_bins,
        occupancy_percent=snapshot.occupancy_percent,
        waves=[
            WmsCockpitWaveResponse.model_validate(value, from_attributes=True)
            for value in snapshot.waves
        ],
        zones=[
            WmsZoneOccupancyResponse.model_validate(value, from_attributes=True)
            for value in snapshot.zones
        ],
        dispatch_queue=[
            WmsDispatchQueueResponse.model_validate(value, from_attributes=True)
            for value in snapshot.dispatch_queue
        ],
    )


__all__ = ["get_wms_cockpit", "router"]
