"""HTTP endpoint for the read-only multichannel Sales cockpit."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.api.schemas import (
    SalesChannelPulseResponse,
    SalesCockpitOrderResponse,
    SalesCockpitResponse,
)
from erp.modules.sales.application import SalesCockpitService
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/sales", tags=["sales"])


def get_sales_cockpit(request: Request) -> SalesCockpitService:
    service = getattr(request.app.state, "sales_channel_cockpit", None)
    if not isinstance(service, SalesCockpitService):
        raise ApplicationError(
            code="SALES_COCKPIT_UNAVAILABLE",
            message="Sales cockpit service unavailable.",
            status_code=503,
        )
    return service


@router.get("/cockpit", response_model=SalesCockpitResponse)
async def get_cockpit_snapshot(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SalesCockpitService, Depends(get_sales_cockpit)],
    company_id: UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SalesCockpitResponse:
    snapshot = await service.snapshot(context, company_id, limit=limit)
    response.headers["Cache-Control"] = "no-store"
    return SalesCockpitResponse(
        company_id=snapshot.company_id,
        generated_at=snapshot.generated_at,
        reconciled_orders=snapshot.reconciled_orders,
        margin_pending_orders=snapshot.margin_pending_orders,
        channels=[
            SalesChannelPulseResponse.model_validate(value, from_attributes=True)
            for value in snapshot.channels
        ],
        orders=[
            SalesCockpitOrderResponse.model_validate(value, from_attributes=True)
            for value in snapshot.orders
        ],
    )


__all__ = ["get_sales_cockpit", "router"]
