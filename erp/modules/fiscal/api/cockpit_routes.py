"""Official read-only fiscal cockpit endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.contracts import SecurityContext
from erp.modules.fiscal.api.cockpit_schemas import FiscalCockpitResponse
from erp.modules.fiscal.api.routes import resolve_security_context
from erp.modules.fiscal.application import FiscalCockpitService
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/fiscal", tags=["fiscal-cockpit"])


def get_fiscal_cockpit(request: Request) -> FiscalCockpitService:
    service = getattr(request.app.state, "fiscal_cockpit", None)
    if not isinstance(service, FiscalCockpitService):
        raise ApplicationError(
            code="FISCAL_COCKPIT_UNAVAILABLE",
            message="Fiscal cockpit service unavailable.",
            status_code=503,
        )
    return service


@router.get("/cockpit", response_model=FiscalCockpitResponse)
async def get_cockpit_snapshot(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[FiscalCockpitService, Depends(get_fiscal_cockpit)],
    company_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> FiscalCockpitResponse:
    snapshot = await service.snapshot(context, company_id, limit=limit)
    response.headers["Cache-Control"] = "no-store"
    return FiscalCockpitResponse.model_validate(snapshot, from_attributes=True)


__all__ = ["get_fiscal_cockpit", "router"]
