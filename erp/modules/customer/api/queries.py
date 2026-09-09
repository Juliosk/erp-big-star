"""Read-only customer endpoints with explicit company context."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.api.schemas import CustomerListResponse, CustomerResponse, PageMetadata
from erp.modules.customer.application import CustomerQueries
from erp.modules.customer.domain import CustomerStatus, CustomerType
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/customers", tags=["customer-core"])


def get_queries(request: Request) -> CustomerQueries:
    service = getattr(request.app.state, "customer_queries", None)
    if not isinstance(service, CustomerQueries):
        raise ApplicationError(
            code="CUSTOMER_QUERY_UNAVAILABLE",
            message="Customer queries unavailable.",
            status_code=503,
        )
    return service


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CustomerQueries, Depends(get_queries)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    status: CustomerStatus | None = None,
    customer_type: CustomerType | None = None,
) -> CustomerListResponse:
    result = await service.list(
        context,
        company_id,
        page=page,
        page_size=page_size,
        status=status,
        customer_type=customer_type,
    )
    response.headers["Cache-Control"] = "no-store"
    return CustomerListResponse(
        data=[CustomerResponse.model_validate(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[CustomerQueries, Depends(get_queries)],
) -> CustomerResponse:
    customer = await service.get(context, company_id, customer_id)
    response.headers["ETag"] = f'"{customer.version}"'
    response.headers["Cache-Control"] = "no-store"
    return CustomerResponse.model_validate(customer)


__all__ = ["router"]
