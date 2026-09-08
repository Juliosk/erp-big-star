"""Official GET/POST barcode routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.product.api.creation import ProductCommandResponse, metadata
from erp.modules.product.api.versioning import require_version
from erp.modules.product.application.barcodes import AddBarcode, ProductBarcodeService
from erp.modules.product.domain.barcode import BarcodeType
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/products", tags=["product-master"])


class BarcodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    barcode_type: BarcodeType
    barcode: str = Field(min_length=1, max_length=64)


class BarcodeResponse(BarcodeRequest):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    product_id: UUID


class BarcodeCommandResponse(ProductCommandResponse):
    barcode: BarcodeResponse


class BarcodeListResponse(BaseModel):
    data: list[BarcodeResponse]


def get_barcodes(request: Request) -> ProductBarcodeService:
    service = getattr(request.app.state, "product_barcodes", None)
    if not isinstance(service, ProductBarcodeService):
        raise ApplicationError(
            code="PRODUCT_COMMAND_UNAVAILABLE",
            message="Barcode service unavailable.",
            status_code=503,
        )
    return service


@router.get("/{product_id}/barcodes", response_model=BarcodeListResponse)
async def list_barcodes(
    product_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[ProductBarcodeService, Depends(get_barcodes)],
) -> BarcodeListResponse:
    items = await service.list(context, company_id, product_id)
    response.headers["Cache-Control"] = "no-store"
    return BarcodeListResponse(data=[BarcodeResponse.model_validate(item) for item in items])


@router.post("/{product_id}/barcodes", status_code=201, response_model=BarcodeCommandResponse)
async def add_barcode(
    product_id: UUID,
    company_id: UUID,
    body: BarcodeRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[ProductBarcodeService, Depends(get_barcodes)],
    version: Annotated[int, Depends(require_version)],
    key: Annotated[str, Depends(require_idempotency_key)],
) -> BarcodeCommandResponse:
    result = await service.add(
        context,
        AddBarcode(
            company_id, product_id, body.barcode_type, body.barcode, version, key, metadata(request)
        ),
    )
    response.headers["ETag"] = f'"{result.result.product.version}"'
    response.headers["Idempotency-Replayed"] = str(result.result.idempotency_replayed).lower()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/api/v1/products/{product_id}/barcodes?company_id={company_id}"
    return BarcodeCommandResponse.model_validate(result.to_dict())


__all__ = ["router"]
