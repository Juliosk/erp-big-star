"""Official read-only procurement cockpit endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.contracts import SecurityContext
from erp.modules.procurement.api.cockpit_schemas import ProcurementCockpitResponse
from erp.modules.procurement.api.routes import resolve_security_context
from erp.modules.procurement.application import ProcurementCockpitService
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/procurement", tags=["procurement-cockpit"])


def get_procurement_cockpit(request: Request) -> ProcurementCockpitService:
    service = getattr(request.app.state, "procurement_cockpit", None)
    if not isinstance(service, ProcurementCockpitService):
        raise ApplicationError(
            code="PROCUREMENT_COCKPIT_UNAVAILABLE",
            message="Procurement cockpit service unavailable.",
            status_code=503,
        )
    return service


@router.get("/cockpit", response_model=ProcurementCockpitResponse)
async def get_cockpit_snapshot(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[ProcurementCockpitService, Depends(get_procurement_cockpit)],
    company_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> ProcurementCockpitResponse:
    snapshot = await service.snapshot(context, company_id, limit=limit)
    response.headers["Cache-Control"] = "no-store"
    return ProcurementCockpitResponse.model_validate(snapshot, from_attributes=True)


__all__ = ["get_procurement_cockpit", "router"]
