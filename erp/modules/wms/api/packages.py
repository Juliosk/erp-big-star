"""Package HTTP endpoints for M10 WMS packing."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.wms.api.schemas import (
    AddPackageItemRequest,
    CreatePackageRequest,
    PackageDetailResponse,
    PackageItemResponse,
    PackageResponse,
)
from erp.modules.wms.api.versioning import require_version
from erp.modules.wms.application import (
    AddPackageItem,
    CreatePackage,
    PackageCommand,
    PackingService,
)
from erp.modules.wms.domain.package import Package, PackageItem
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/wms", tags=["wms"])


def get_packing(request: Request) -> PackingService:
    service = getattr(request.app.state, "wms_packing", None)
    if not isinstance(service, PackingService):
        raise ApplicationError(
            code="WMS_PACKING_UNAVAILABLE",
            message="WMS packing service unavailable.",
            status_code=503,
        )
    return service


@router.post("/packages", status_code=201, response_model=PackageDetailResponse)
async def create_package(
    body: CreatePackageRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PackingService, Depends(get_packing)],
) -> PackageDetailResponse:
    result = await service.create_package(
        context,
        CreatePackage(
            company_id=body.company_id,
            package_code=body.package_code,
            package_type=body.package_type,
            wave_id=body.wave_id,
            shipment_id=body.shipment_id,
            weight_grams=body.weight_grams,
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/wms/packages/{result.package.id}?company_id={result.package.company_id}"
    )
    response.headers["ETag"] = f'"{result.package.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _detail_response(result.package, result.items)


@router.get("/packages/{package_id}", response_model=PackageDetailResponse)
async def get_package(
    package_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PackingService, Depends(get_packing)],
) -> PackageDetailResponse:
    result = await service.get_package(context, company_id, package_id)
    response.headers["ETag"] = f'"{result.package.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _detail_response(result.package, result.items)


@router.post("/packages/{package_id}/items", response_model=PackageDetailResponse)
async def add_package_item(
    package_id: UUID,
    company_id: UUID,
    body: AddPackageItemRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PackingService, Depends(get_packing)],
) -> PackageDetailResponse:
    result = await service.add_item(
        context,
        AddPackageItem(
            company_id=company_id,
            package_id=package_id,
            task_id=body.task_id,
            product_id=body.product_id,
            lot_id=body.lot_id,
            quantity=body.quantity,
        ),
    )
    response.headers["ETag"] = f'"{result.package.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _detail_response(result.package, result.items)


@router.post("/packages/{package_id}/verify", response_model=PackageDetailResponse)
async def verify_package(
    package_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PackingService, Depends(get_packing)],
    expected_version: Annotated[int, Depends(require_version)],
) -> PackageDetailResponse:
    result = await service.verify_package(
        context,
        PackageCommand(
            company_id=company_id,
            package_id=package_id,
            expected_version=expected_version,
        ),
    )
    response.headers["ETag"] = f'"{result.package.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _detail_response(result.package, result.items)


@router.post("/packages/{package_id}/finalize", response_model=PackageDetailResponse)
async def finalize_package(
    package_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PackingService, Depends(get_packing)],
    expected_version: Annotated[int, Depends(require_version)],
) -> PackageDetailResponse:
    result = await service.finalize_package(
        context,
        PackageCommand(
            company_id=company_id,
            package_id=package_id,
            expected_version=expected_version,
        ),
    )
    response.headers["ETag"] = f'"{result.package.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _detail_response(result.package, result.items)


def _detail_response(package: Package, items: tuple[PackageItem, ...]) -> PackageDetailResponse:
    return PackageDetailResponse(
        package=_package_response(package),
        items=[_item_response(item) for item in items],
    )


def _package_response(package: Package) -> PackageResponse:
    return PackageResponse(
        id=package.id,
        company_id=package.company_id,
        package_code=package.package_code,
        package_type=package.package_type,
        status=package.status,
        wave_id=package.wave_id,
        shipment_id=package.shipment_id,
        weight_grams=package.weight_grams,
        version=package.version,
    )


def _item_response(item: PackageItem) -> PackageItemResponse:
    return PackageItemResponse(
        id=item.id,
        company_id=item.company_id,
        package_id=item.package_id,
        task_id=item.task_id,
        product_id=item.product_id,
        lot_id=item.lot_id,
        quantity=f"{item.quantity:.6f}",
    )


__all__ = ["get_packing", "router"]
