"""Read-only product endpoints with explicit company context."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.product.api.schemas import PageMetadata, ProductListResponse, ProductResponse
from erp.modules.product.application import ProductQueries
from erp.modules.product.domain import ProductLifecycle
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/products", tags=["product-master"])


def get_queries(request: Request) -> ProductQueries:
    service = getattr(request.app.state, "product_queries", None)
    if not isinstance(service, ProductQueries):
        raise ApplicationError(
            code="PRODUCT_QUERY_UNAVAILABLE",
            message="Product queries unavailable.",
            status_code=503,
        )
    return service


@router.get("", response_model=ProductListResponse)
async def list_products(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[ProductQueries, Depends(get_queries)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    lifecycle: ProductLifecycle | None = None,
) -> ProductListResponse:
    result = await service.list(
        context, company_id, page=page, page_size=page_size, lifecycle=lifecycle
    )
    response.headers["Cache-Control"] = "no-store"
    return ProductListResponse(
        data=[ProductResponse.model_validate(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[ProductQueries, Depends(get_queries)],
) -> ProductResponse:
    product = await service.get(context, company_id, product_id)
    response.headers["ETag"] = f'"{product.version}"'
    response.headers["Cache-Control"] = "no-store"
    return ProductResponse.model_validate(product)


__all__ = ["router"]
