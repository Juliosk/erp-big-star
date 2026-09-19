"""M15 sales quote REST endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.api.schemas import (
    CreateSalesQuoteRequest,
    PageMetadata,
    QuoteItemResponse,
    QuoteRevisionResponse,
    SalesQuoteDetailResponse,
    SalesQuoteListResponse,
    SalesQuoteResponse,
)
from erp.modules.sales.application import CreateSalesQuote, SalesQuoteDetail, SalesQuoteService
from erp.modules.sales.domain import SalesQuote, SalesQuoteStatus
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/sales/quotes", tags=["sales"])


def get_sales_quotes(request: Request) -> SalesQuoteService:
    service = getattr(request.app.state, "sales_quotes", None)
    if not isinstance(service, SalesQuoteService):
        raise ApplicationError(
            code="SALES_QUOTE_UNAVAILABLE",
            message="Sales quote service unavailable.",
            status_code=503,
        )
    return service


@router.post("", status_code=201, response_model=SalesQuoteResponse)
async def create_quote(
    body: CreateSalesQuoteRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SalesQuoteService, Depends(get_sales_quotes)],
) -> SalesQuoteResponse:
    quote = await service.create(
        context,
        CreateSalesQuote(body.company_id, body.number, body.customer_id, body.currency),
    )
    response.headers["Location"] = f"/api/v1/sales/quotes/{quote.id}?company_id={quote.company_id}"
    _headers(response, quote)
    return _quote(quote)


@router.get("", response_model=SalesQuoteListResponse)
async def list_quotes(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SalesQuoteService, Depends(get_sales_quotes)],
    company_id: UUID,
    status: SalesQuoteStatus | None = None,
    customer_id: UUID | None = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SalesQuoteListResponse:
    result = await service.list(
        context,
        company_id,
        status=status,
        customer_id=customer_id,
        page=page,
        page_size=page_size,
    )
    response.headers["Cache-Control"] = "no-store"
    return SalesQuoteListResponse(
        data=[_quote(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.get("/{quote_id}", response_model=SalesQuoteDetailResponse)
async def get_quote(
    quote_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SalesQuoteService, Depends(get_sales_quotes)],
) -> SalesQuoteDetailResponse:
    detail = await service.get(context, company_id, quote_id)
    _headers(response, detail.quote)
    return _detail(detail)


def _quote(quote: SalesQuote) -> SalesQuoteResponse:
    return SalesQuoteResponse(**{field: getattr(quote, field) for field in SalesQuoteResponse.model_fields})


def _detail(detail: SalesQuoteDetail) -> SalesQuoteDetailResponse:
    return SalesQuoteDetailResponse(
        quote=_quote(detail.quote),
        revisions=[
            QuoteRevisionResponse(
                id=revision.id,
                revision_number=revision.revision_number,
                gross_amount=revision.gross_amount,
                discount_amount=revision.discount_amount,
                net_amount=revision.net_amount,
                pricing_snapshot_refs=list(revision.pricing_snapshot_refs),
                items=[
                    QuoteItemResponse(
                        id=item.id,
                        product_id=item.product_id,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        discount_amount=item.discount_amount,
                    )
                    for item in revision.items
                ],
            )
            for revision in detail.revisions
        ],
    )


def _headers(response: Response, quote: SalesQuote) -> None:
    response.headers["ETag"] = f'"{quote.version}"'
    response.headers["Cache-Control"] = "no-store"


__all__ = ["router"]
