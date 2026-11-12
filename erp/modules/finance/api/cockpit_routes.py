"""Official read-only finance governance cockpit endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.contracts import SecurityContext
from erp.modules.finance.api.cockpit_schemas import FinanceCockpitResponse
from erp.modules.finance.api.routes import resolve_security_context
from erp.modules.finance.application import FinanceCockpitService
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/finance", tags=["finance-cockpit"])


def get_finance_cockpit(request: Request) -> FinanceCockpitService:
    service = getattr(request.app.state, "finance_cockpit", None)
    if not isinstance(service, FinanceCockpitService):
        raise ApplicationError(
            code="FINANCE_COCKPIT_UNAVAILABLE",
            message="Finance cockpit service unavailable.",
            status_code=503,
        )
    return service


@router.get("/cockpit", response_model=FinanceCockpitResponse)
async def get_cockpit_snapshot(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[FinanceCockpitService, Depends(get_finance_cockpit)],
    company_id: UUID,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> FinanceCockpitResponse:
    snapshot = await service.snapshot(context, company_id, limit=limit)
    response.headers["Cache-Control"] = "no-store"
    return FinanceCockpitResponse.model_validate(snapshot, from_attributes=True)


__all__ = ["get_finance_cockpit", "router"]
