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
    ReviseSalesQuoteRequest,
    SalesQuoteDetailResponse,
    SalesQuoteListResponse,
    SalesQuoteMutationResponse,
    SalesQuoteResponse,
    TransitionSalesQuoteRequest,
)
from erp.modules.sales.api.versioning import require_version
from erp.modules.sales.application import (
    CommandMetadata,
    CreateSalesQuote,
    ReviseSalesQuote,
    RevisionLine,
    SalesQuoteDetail,
    SalesQuoteLifecycleService,
    SalesQuoteService,
    TransitionSalesQuote,
)
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


def get_sales_quote_lifecycle(request: Request) -> SalesQuoteLifecycleService:
    service = getattr(request.app.state, "sales_quote_lifecycle", None)
    if not isinstance(service, SalesQuoteLifecycleService):
        raise ApplicationError(
            code="SALES_QUOTE_LIFECYCLE_UNAVAILABLE",
            message="Sales quote lifecycle service unavailable.",
            status_code=503,
        )
    return service


def metadata(request: Request) -> CommandMetadata:
    return CommandMetadata(
        UUID(request.state.request_id),
        UUID(request.state.correlation_id),
        request.client.host if request.client is not None else None,
    )


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


@router.post("/{quote_id}/revisions", response_model=SalesQuoteMutationResponse)
async def revise_quote(
    quote_id: UUID,
    body: ReviseSalesQuoteRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[SalesQuoteLifecycleService, Depends(get_sales_quote_lifecycle)],
    expected_version: Annotated[int, Depends(require_version)],
) -> SalesQuoteMutationResponse:
    result = await service.revise(
        context,
        ReviseSalesQuote(
            body.company_id,
            quote_id,
            expected_version,
            tuple(
                RevisionLine(
                    line.product_id,
                    line.quantity,
                    line.unit_price,
                    line.discount_amount,
                    line.pricing_snapshot_id,
                )
                for line in body.lines
            ),
            metadata(request),
        ),
    )
    _headers(response, result.detail.quote)
    return SalesQuoteMutationResponse(
        detail=_detail(result.detail), event_id=result.event_id, audit_event_id=result.audit_event_id
    )


async def _transition_endpoint(
    quote_id: UUID,
    body: TransitionSalesQuoteRequest,
    request: Request,
    response: Response,
    context: SecurityContext,
    service: SalesQuoteLifecycleService,
    expected_version: int,
    target: SalesQuoteStatus,
) -> SalesQuoteMutationResponse:
    result = await service.transition(
        context,
        TransitionSalesQuote(
            body.company_id,
            quote_id,
            expected_version,
            target,
            metadata(request),
            body.reason_code,
        ),
    )
    _headers(response, result.detail.quote)
    return SalesQuoteMutationResponse(
        detail=_detail(result.detail), event_id=result.event_id, audit_event_id=result.audit_event_id
    )


def _transition_route(path: str, target: SalesQuoteStatus) -> None:
    async def endpoint(
        quote_id: UUID,
        body: TransitionSalesQuoteRequest,
        request: Request,
        response: Response,
        context: Annotated[SecurityContext, Depends(resolve_security_context)],
        service: Annotated[SalesQuoteLifecycleService, Depends(get_sales_quote_lifecycle)],
        expected_version: Annotated[int, Depends(require_version)],
    ) -> SalesQuoteMutationResponse:
        return await _transition_endpoint(
            quote_id, body, request, response, context, service, expected_version, target
        )

    router.add_api_route(
        f"/{{quote_id}}/{path}", endpoint, methods=["POST"], response_model=SalesQuoteMutationResponse
    )


_transition_route("send", SalesQuoteStatus.SENT)
_transition_route("accept", SalesQuoteStatus.ACCEPTED)
_transition_route("accept-partially", SalesQuoteStatus.PARTIALLY_ACCEPTED)
_transition_route("lost", SalesQuoteStatus.LOST)


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
