"""Inventory catalogue creation endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.api.schemas import (
    CreateInventoryLotRequest,
    CreateInventoryPoolRequest,
    CreateLocationRequest,
    CreateWarehouseRequest,
    InventoryLotResponse,
    InventoryPoolResponse,
    WarehouseLocationResponse,
    WarehouseResponse,
)
from erp.modules.inventory.application.catalogue import InventoryCatalogService
from erp.modules.inventory.application.commands import (
    CommandMetadata,
    CreateInventoryLot,
    CreateInventoryPool,
    CreateLocation,
    CreateWarehouse,
)
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


def get_creation(request: Request) -> InventoryCatalogService:
    service = getattr(request.app.state, "inventory_creation", None)
    if not isinstance(service, InventoryCatalogService):
        raise ApplicationError(
            code="INVENTORY_COMMAND_UNAVAILABLE",
            message="Inventory commands unavailable.",
            status_code=503,
        )
    return service


def metadata(request: Request) -> CommandMetadata:
    return CommandMetadata(
        UUID(request.state.request_id),
        UUID(request.state.correlation_id),
        request.client.host if request.client is not None else None,
    )


@router.post("/warehouses", status_code=201, response_model=WarehouseResponse)
async def create_warehouse(
    body: CreateWarehouseRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryCatalogService, Depends(get_creation)],
) -> WarehouseResponse:
    result = await service.create_warehouse(
        context,
        CreateWarehouse(
            company_id=body.company_id,
            branch_id=body.branch_id,
            code=body.code,
            name=body.name,
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/inventory/warehouses/{result.id}?company_id={result.company_id}"
    )
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return WarehouseResponse.model_validate(result)


@router.post("/locations", status_code=201, response_model=WarehouseLocationResponse)
async def create_location(
    body: CreateLocationRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryCatalogService, Depends(get_creation)],
) -> WarehouseLocationResponse:
    result = await service.create_location(
        context,
        CreateLocation(
            company_id=body.company_id,
            warehouse_id=body.warehouse_id,
            code=body.code,
            name=body.name,
            parent_location_id=body.parent_location_id,
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/inventory/locations/{result.id}?company_id={result.company_id}"
    )
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return WarehouseLocationResponse.model_validate(result)


@router.post("/pools", status_code=201, response_model=InventoryPoolResponse)
async def create_pool(
    body: CreateInventoryPoolRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryCatalogService, Depends(get_creation)],
) -> InventoryPoolResponse:
    result = await service.create_pool(
        context,
        CreateInventoryPool(
            company_id=body.company_id,
            code=body.code,
            name=body.name,
            kind=body.kind,
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/inventory/pools/{result.id}?company_id={result.company_id}"
    )
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return InventoryPoolResponse.model_validate(result)


@router.post("/lots", status_code=201, response_model=InventoryLotResponse)
async def create_lot(
    body: CreateInventoryLotRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryCatalogService, Depends(get_creation)],
) -> InventoryLotResponse:
    result = await service.create_lot(
        context,
        CreateInventoryLot(
            company_id=body.company_id,
            product_id=body.product_id,
            code=body.code,
            expires_on=body.expires_on,
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/inventory/lots/{result.id}?company_id={result.company_id}"
    )
    response.headers["ETag"] = f'"{result.version}"'
    response.headers["Cache-Control"] = "no-store"
    return InventoryLotResponse.model_validate(result)


__all__ = ["get_creation", "metadata", "router"]
