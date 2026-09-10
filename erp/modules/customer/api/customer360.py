"""Customer 360 HTTP endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.api.schemas import Customer360Response
from erp.modules.customer.application.customer360 import Customer360Service
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/customers", tags=["customer-core"])


def get_customer360(request: Request) -> Customer360Service:
    service = getattr(request.app.state, "customer_360", None)
    if not isinstance(service, Customer360Service):
        raise ApplicationError(
            code="CUSTOMER_360_UNAVAILABLE",
            message="Customer 360 unavailable.",
            status_code=503,
        )
    return service


@router.get("/{customer_id}/360", response_model=Customer360Response)
async def get_customer_360(
    customer_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[Customer360Service, Depends(get_customer360)],
) -> Customer360Response:
    snapshot = await service.get(context, company_id, customer_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["ETag"] = f'"{snapshot.customer.version}"'
    return Customer360Response.from_snapshot(snapshot)


__all__ = ["router"]
