"""Read-only inventory catalogue endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.api.schemas import (
    InventoryBalanceListResponse,
    InventoryBalanceResponse,
    InventoryLotListResponse,
    InventoryLotResponse,
    InventoryPoolListResponse,
    InventoryPoolResponse,
    InventoryPostingListResponse,
    InventoryPostingResponse,
    PageMetadata,
    WarehouseListResponse,
    WarehouseLocationListResponse,
    WarehouseLocationResponse,
    WarehouseResponse,
)
from erp.modules.inventory.application.queries import InventoryQueries
from erp.modules.inventory.domain import (
    InventoryBalance,
    InventoryLotStatus,
    InventoryPosting,
    InventoryState,
)
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


def get_queries(request: Request) -> InventoryQueries:
    service = getattr(request.app.state, "inventory_queries", None)
    if not isinstance(service, InventoryQueries):
        raise ApplicationError(
            code="INVENTORY_QUERY_UNAVAILABLE",
            message="Inventory queries unavailable.",
            status_code=503,
        )
    return service


@router.get("/warehouses", response_model=WarehouseListResponse)
async def list_warehouses(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryQueries, Depends(get_queries)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    active: bool | None = None,
) -> WarehouseListResponse:
    result = await service.list_warehouses(
        context, company_id, page=page, page_size=page_size, active=active
    )
    response.headers["Cache-Control"] = "no-store"
    return WarehouseListResponse(
        data=[WarehouseResponse.model_validate(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.get("/warehouses/{warehouse_id}", response_model=WarehouseResponse)
async def get_warehouse(
    warehouse_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryQueries, Depends(get_queries)],
) -> WarehouseResponse:
    result = await service.get_warehouse(context, company_id, warehouse_id)
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return WarehouseResponse.model_validate(result)


@router.get("/locations", response_model=WarehouseLocationListResponse)
async def list_locations(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryQueries, Depends(get_queries)],
    company_id: UUID,
    warehouse_id: UUID | None = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    active: bool | None = None,
) -> WarehouseLocationListResponse:
    result = await service.list_locations(
        context,
        company_id,
        warehouse_id=warehouse_id,
        page=page,
        page_size=page_size,
        active=active,
    )
    response.headers["Cache-Control"] = "no-store"
    return WarehouseLocationListResponse(
        data=[WarehouseLocationResponse.model_validate(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.get("/locations/{location_id}", response_model=WarehouseLocationResponse)
async def get_location(
    location_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryQueries, Depends(get_queries)],
) -> WarehouseLocationResponse:
    result = await service.get_location(context, company_id, location_id)
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return WarehouseLocationResponse.model_validate(result)


@router.get("/pools", response_model=InventoryPoolListResponse)
async def list_pools(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryQueries, Depends(get_queries)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    active: bool | None = None,
) -> InventoryPoolListResponse:
    result = await service.list_pools(
        context, company_id, page=page, page_size=page_size, active=active
    )
    response.headers["Cache-Control"] = "no-store"
    return InventoryPoolListResponse(
        data=[InventoryPoolResponse.model_validate(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.get("/pools/{pool_id}", response_model=InventoryPoolResponse)
async def get_pool(
    pool_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryQueries, Depends(get_queries)],
) -> InventoryPoolResponse:
    result = await service.get_pool(context, company_id, pool_id)
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return InventoryPoolResponse.model_validate(result)


@router.get("/lots", response_model=InventoryLotListResponse)
async def list_lots(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryQueries, Depends(get_queries)],
    company_id: UUID,
    product_id: UUID | None = None,
    status: InventoryLotStatus | None = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> InventoryLotListResponse:
    result = await service.list_lots(
        context,
        company_id,
        product_id=product_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    response.headers["Cache-Control"] = "no-store"
    return InventoryLotListResponse(
        data=[InventoryLotResponse.model_validate(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.get("/lots/{lot_id}", response_model=InventoryLotResponse)
async def get_lot(
    lot_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryQueries, Depends(get_queries)],
) -> InventoryLotResponse:
    result = await service.get_lot(context, company_id, lot_id)
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return InventoryLotResponse.model_validate(result)


@router.get("/balances", response_model=InventoryBalanceListResponse)
async def list_balances(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryQueries, Depends(get_queries)],
    company_id: UUID,
    product_id: UUID | None = None,
    warehouse_id: UUID | None = None,
    lot_id: UUID | None = None,
    state: InventoryState | None = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> InventoryBalanceListResponse:
    result = await service.list_balances(
        context,
        company_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        lot_id=lot_id,
        state=state,
        page=page,
        page_size=page_size,
    )
    response.headers["Cache-Control"] = "no-store"
    return InventoryBalanceListResponse(
        data=[_balance_response(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.get("/lots/{lot_id}/postings", response_model=InventoryPostingListResponse)
async def list_lot_postings(
    lot_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryQueries, Depends(get_queries)],
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> InventoryPostingListResponse:
    result = await service.list_lot_postings(
        context, company_id, lot_id, page=page, page_size=page_size
    )
    response.headers["Cache-Control"] = "no-store"
    return InventoryPostingListResponse(
        data=[_posting_response(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


def _balance_response(balance: InventoryBalance) -> InventoryBalanceResponse:
    return InventoryBalanceResponse(
        id=balance.id,
        company_id=balance.company_id,
        product_id=balance.product_id,
        warehouse_id=balance.warehouse_id,
        location_id=balance.location_id,
        lot_id=balance.lot_id,
        pool_id=balance.pool_id,
        state=balance.state.value,
        quantity=f"{balance.quantity.value:.6f}",
        version=balance.version,
    )


def _posting_response(posting: InventoryPosting) -> InventoryPostingResponse:
    return InventoryPostingResponse(
        id=posting.id,
        company_id=posting.company_id,
        transaction_id=posting.transaction_id,
        sequence=posting.sequence,
        product_id=posting.product_id,
        warehouse_id=posting.warehouse_id,
        location_id=posting.location_id,
        lot_id=posting.lot_id,
        pool_id=posting.pool_id,
        state=posting.state.value,
        quantity_delta=f"{posting.quantity_delta:.6f}",
    )


__all__ = ["get_queries", "router"]
