"""Official conversion and Sales Order endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.contracts import InventoryReservationKindContract
from erp.modules.sales.api.routes import metadata
from erp.modules.sales.api.schemas import (
    ConvertQuoteToOrderRequest,
    PageMetadata,
    ReserveSalesOrderRequest,
    SalesOrderConversionResponse,
    SalesOrderItemResponse,
    SalesOrderListResponse,
    SalesOrderReservationLineResponse,
    SalesOrderReservationResponse,
    SalesOrderResponse,
)
from erp.modules.sales.api.versioning import require_version
from erp.modules.sales.application import (
    ConvertQuoteToOrder,
    ReserveSalesOrder,
    SalesOrderConversionService,
    SalesOrderReservationService,
    SalesOrderService,
)
from erp.modules.sales.domain import SalesOrder, SalesOrderReservation
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


def get_order_reservations(request: Request) -> SalesOrderReservationService:
    service = getattr(request.app.state, "sales_order_reservations", None)
    if not isinstance(service, SalesOrderReservationService):
        raise ApplicationError(
            code="SALES_ORDER_RESERVATION_UNAVAILABLE",
            message="Sales order reservation service unavailable.",
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


@router.post(
    "/orders/{order_id}/reserve",
    status_code=201,
    response_model=SalesOrderReservationResponse,
)
async def reserve_order(
    order_id: UUID,
    body: ReserveSalesOrderRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SalesOrderReservationService, Depends(get_order_reservations)],
    expected_version: Annotated[int, Depends(require_version)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> SalesOrderReservationResponse:
    try:
        reservation_kind = InventoryReservationKindContract(body.reservation_kind)
    except ValueError as error:
        raise ApplicationError(
            code="BUSINESS_VALIDATION_ERROR",
            message="Invalid reservation kind.",
            status_code=422,
        ) from error
    result = await service.reserve(
        context,
        ReserveSalesOrder(
            company_id=body.company_id,
            order_id=order_id,
            warehouse_id=body.warehouse_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            metadata=metadata(request),
            location_id=body.location_id,
            lot_id=body.lot_id,
            pool_id=body.pool_id,
            reservation_kind=reservation_kind,
            expires_at=body.expires_at,
        ),
    )
    response.headers["ETag"] = f'"{result.reservation.version}"'
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    response.headers["Cache-Control"] = "no-store"
    return _reservation(
        result.reservation,
        inventory_event_id=result.inventory_event_id,
        audit_event_id=result.audit_event_id,
        idempotency_replayed=result.idempotency_replayed,
    )


@router.get(
    "/orders/{order_id}/reservation",
    response_model=SalesOrderReservationResponse,
)
async def get_order_reservation(
    order_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SalesOrderReservationService, Depends(get_order_reservations)],
) -> SalesOrderReservationResponse:
    reservation = await service.get(context, company_id, order_id)
    response.headers["ETag"] = f'"{reservation.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _reservation(reservation)


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


def _reservation(
    reservation: SalesOrderReservation,
    *,
    inventory_event_id: UUID | None = None,
    audit_event_id: UUID | None = None,
    idempotency_replayed: bool = False,
) -> SalesOrderReservationResponse:
    return SalesOrderReservationResponse(
        id=reservation.id,
        company_id=reservation.company_id,
        order_id=reservation.order_id,
        inventory_reservation_id=reservation.inventory_reservation_id,
        status=reservation.status,
        order_version=reservation.order_version,
        version=reservation.version,
        lines=[
            SalesOrderReservationLineResponse(
                order_item_id=line.order_item_id,
                product_id=line.product_id,
                quantity=line.quantity,
                pricing_snapshot_id=line.pricing_snapshot_id,
            )
            for line in reservation.lines
        ],
        inventory_event_id=inventory_event_id,
        audit_event_id=audit_event_id,
        idempotency_replayed=idempotency_replayed,
    )


__all__ = ["router"]
