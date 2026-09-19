"""Official conversion and Sales Order endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.api.routes import metadata
from erp.modules.sales.api.schemas import (
    ConvertQuoteToOrderRequest,
    PageMetadata,
    SalesOrderConversionResponse,
    SalesOrderItemResponse,
    SalesOrderListResponse,
    SalesOrderResponse,
)
from erp.modules.sales.api.versioning import require_version
from erp.modules.sales.application import (
    ConvertQuoteToOrder,
    SalesOrderConversionService,
    SalesOrderService,
)
from erp.modules.sales.domain import SalesOrder
from erp.platform.errors import ApplicationError
from erp.platform.idempotency.http import require_idempotency_key

router = APIRouter(prefix="/api/v1/sales", tags=["sales"])


def get_conversion(request: Request) -> SalesOrderConversionService:
    service = getattr(request.app.state, "sales_order_conversion", None)
    if not isinstance(service, SalesOrderConversionService):
        raise ApplicationError(
            code="SALES_ORDER_CONVERSION_UNAVAILABLE",
            message="Sales order conversion service unavailable.",
            status_code=503,
        )
    return service


def get_orders(request: Request) -> SalesOrderService:
    service = getattr(request.app.state, "sales_orders", None)
    if not isinstance(service, SalesOrderService):
        raise ApplicationError(
            code="SALES_ORDER_UNAVAILABLE",
            message="Sales order service unavailable.",
            status_code=503,
        )
    return service


@router.post(
    "/quotes/{quote_id}/convert-to-order",
    status_code=201,
    response_model=SalesOrderConversionResponse,
)
async def convert_quote_to_order(
    quote_id: UUID,
    body: ConvertQuoteToOrderRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SalesOrderConversionService, Depends(get_conversion)],
    expected_version: Annotated[int, Depends(require_version)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> SalesOrderConversionResponse:
    result = await service.convert(
        context,
        ConvertQuoteToOrder(
            body.company_id,
            quote_id,
            body.order_number,
            expected_version,
            idempotency_key,
            metadata(request),
        ),
    )
    response.headers["Location"] = f"/api/v1/sales/orders/{result.order.id}?company_id={result.order.company_id}"
    response.headers["ETag"] = f'"{result.order.version}"'
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    response.headers["Cache-Control"] = "no-store"
    return SalesOrderConversionResponse(
        order=_order(result.order),
        quote_version=result.quote_version,
        event_id=result.event_id,
        audit_event_id=result.audit_event_id,
        idempotency_replayed=result.idempotency_replayed,
    )


@router.get("/orders", response_model=SalesOrderListResponse)
async def list_orders(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SalesOrderService, Depends(get_orders)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SalesOrderListResponse:
    result = await service.list(
        context, company_id, page=page, page_size=page_size
    )
    response.headers["Cache-Control"] = "no-store"
    return SalesOrderListResponse(
        data=[_order(item) for item in result.items],
        meta=PageMetadata(
            page=result.page, page_size=result.page_size, has_more=result.has_more
        ),
    )


@router.get("/orders/{order_id}", response_model=SalesOrderResponse)
async def get_order(
    order_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SalesOrderService, Depends(get_orders)],
) -> SalesOrderResponse:
    order = await service.get(context, company_id, order_id)
    response.headers["ETag"] = f'"{order.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _order(order)


def _order(order: SalesOrder) -> SalesOrderResponse:
    return SalesOrderResponse(
        id=order.id,
        company_id=order.company_id,
        number=order.number,
        source_quote_id=order.source_quote_id,
        source_quote_revision_number=order.source_quote_revision_number,
        customer_id=order.customer_id,
        seller_id=order.seller_id,
        currency=order.currency,
        status=order.status,
        gross_amount=order.gross_amount,
        discount_amount=order.discount_amount,
        net_amount=order.net_amount,
        version=order.version,
        items=[
            SalesOrderItemResponse(
                id=item.id,
                quote_revision_item_id=item.quote_revision_item_id,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount_amount=item.discount_amount,
                pricing_snapshot_id=item.pricing_snapshot_id,
            )
            for item in order.items
        ],
    )


__all__ = ["router"]
