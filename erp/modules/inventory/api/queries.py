"""Read-only inventory catalogue endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.api.schemas import (
    InventoryLotListResponse,
    InventoryLotResponse,
    InventoryPoolListResponse,
    InventoryPoolResponse,
    PageMetadata,
    WarehouseListResponse,
    WarehouseLocationListResponse,
    WarehouseLocationResponse,
    WarehouseResponse,
)
from erp.modules.inventory.application.queries import InventoryQueries
from erp.modules.inventory.domain import InventoryLotStatus
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


__all__ = ["get_queries", "router"]
