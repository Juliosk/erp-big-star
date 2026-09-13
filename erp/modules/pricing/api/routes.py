"""M9 pricing catalogue HTTP boundary."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.pricing.api.schemas import (
    CreatePriceListRequest,
    CreatePriceListVersionRequest,
    PageMetadata,
    PriceListItemResponse,
    PriceListListResponse,
    PriceListResponse,
    PriceListVersionCommandResponse,
    PriceListVersionListResponse,
    PriceListVersionResponse,
)
from erp.modules.pricing.api.versioning import require_version
from erp.modules.pricing.application import (
    ActivatePriceListVersion,
    CommandMetadata,
    CreatePriceList,
    CreatePriceListItem,
    CreatePriceListVersion,
    PricingCatalogService,
)
from erp.modules.pricing.domain import (
    PriceList,
    PriceListStatus,
    PriceListVersion,
)
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


def get_catalogue(request: Request) -> PricingCatalogService:
    service = getattr(request.app.state, "pricing_catalogue", None)
    if not isinstance(service, PricingCatalogService):
        raise ApplicationError(
            code="PRICING_UNAVAILABLE",
            message="Pricing catalogue unavailable.",
            status_code=503,
        )
    return service


def metadata(request: Request) -> CommandMetadata:
    return CommandMetadata(
        UUID(request.state.request_id),
        UUID(request.state.correlation_id),
        request.client.host if request.client is not None else None,
    )


@router.get("/price-lists", response_model=PriceListListResponse)
async def list_price_lists(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PricingCatalogService, Depends(get_catalogue)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    status: PriceListStatus | None = None,
) -> PriceListListResponse:
    result = await service.list_price_lists(
        context, company_id, page=page, page_size=page_size, status=status
    )
    response.headers["Cache-Control"] = "no-store"
    return PriceListListResponse(
        data=[_price_list_response(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.post("/price-lists", status_code=201, response_model=PriceListResponse)
async def create_price_list(
    body: CreatePriceListRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PricingCatalogService, Depends(get_catalogue)],
) -> PriceListResponse:
    result = await service.create_price_list(
        context,
        CreatePriceList(
            company_id=body.company_id,
            code=body.code,
            name=body.name,
            price_type=body.price_type,
            currency=body.currency,
        ),
    )
    response.headers["Location"] = f"/api/v1/pricing/price-lists/{result.id}?company_id={result.company_id}"
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _price_list_response(result)


@router.get("/price-lists/{price_list_id}", response_model=PriceListResponse)
async def get_price_list(
    price_list_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PricingCatalogService, Depends(get_catalogue)],
) -> PriceListResponse:
    result = await service.get_price_list(context, company_id, price_list_id)
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _price_list_response(result)


@router.get(
    "/price-lists/{price_list_id}/versions",
    response_model=PriceListVersionListResponse,
)
async def list_price_list_versions(
    price_list_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PricingCatalogService, Depends(get_catalogue)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PriceListVersionListResponse:
    result = await service.list_price_list_versions(
        context, company_id, price_list_id, page=page, page_size=page_size
    )
    response.headers["Cache-Control"] = "no-store"
    return PriceListVersionListResponse(
        data=[_price_list_version_response(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.post(
    "/price-lists/{price_list_id}/versions",
    status_code=201,
    response_model=PriceListVersionResponse,
)
async def create_price_list_version(
    price_list_id: UUID,
    body: CreatePriceListVersionRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PricingCatalogService, Depends(get_catalogue)],
) -> PriceListVersionResponse:
    result = await service.create_price_list_version(
        context,
        CreatePriceListVersion(
            company_id=body.company_id,
            price_list_id=price_list_id,
            valid_from=body.valid_from,
            valid_to=body.valid_to,
            source=body.source,
            items=tuple(
                CreatePriceListItem(
                    product_id=item.product_id,
                    price_amount=item.price_amount,
                    minimum_price_amount=item.minimum_price_amount,
                    target_margin=item.target_margin,
                )
                for item in body.items
            ),
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/pricing/price-list-versions/{result.id}"
        f"?company_id={result.company_id}"
    )
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _price_list_version_response(result)


@router.get("/price-list-versions/{price_list_version_id}", response_model=PriceListVersionResponse)
async def get_price_list_version(
    price_list_version_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PricingCatalogService, Depends(get_catalogue)],
) -> PriceListVersionResponse:
    result = await service.get_price_list_version(context, company_id, price_list_version_id)
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _price_list_version_response(result)


@router.post(
    "/price-list-versions/{price_list_version_id}/activate",
    response_model=PriceListVersionCommandResponse,
)
async def activate_price_list_version(
    price_list_version_id: UUID,
    company_id: UUID,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PricingCatalogService, Depends(get_catalogue)],
    expected_version: Annotated[int, Depends(require_version)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> PriceListVersionCommandResponse:
    result = await service.activate_price_list_version(
        context,
        ActivatePriceListVersion(
            company_id=company_id,
            price_list_version_id=price_list_version_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            metadata=metadata(request),
        ),
    )
    response.headers["ETag"] = f'"{result.price_list_version.version}"'
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    response.headers["Cache-Control"] = "no-store"
    return PriceListVersionCommandResponse(
        price_list_version=_price_list_version_response(result.price_list_version),
        event_id=result.event_id,
        audit_event_id=result.audit_event_id,
        idempotency_replayed=result.idempotency_replayed,
    )


def _price_list_response(price_list: PriceList) -> PriceListResponse:
    return PriceListResponse(
        id=price_list.id,
        company_id=price_list.company_id,
        code=price_list.code,
        name=price_list.name,
        price_type=price_list.price_type,
        currency=price_list.currency,
        status=price_list.status,
        version=price_list.version,
    )


def _price_list_version_response(version: PriceListVersion) -> PriceListVersionResponse:
    return PriceListVersionResponse(
        id=version.id,
        company_id=version.company_id,
        price_list_id=version.price_list_id,
        version_number=version.version_number,
        status=version.status,
        valid_from=version.valid_from,
        valid_to=version.valid_to,
        source=version.source,
        activated_at=version.activated_at,
        version=version.version,
        items=[
            PriceListItemResponse(
                id=item.id,
                product_id=item.product_id,
                price=f"{item.price.amount:.2f}",
                minimum_price=(
                    None if item.minimum_price is None else f"{item.minimum_price.amount:.2f}"
                ),
                target_margin=(
                    None if item.target_margin is None else f"{item.target_margin.value:.4f}"
                ),
                currency=item.price.currency,
            )
            for item in version.items
        ],
    )


__all__ = ["get_catalogue", "metadata", "router"]
