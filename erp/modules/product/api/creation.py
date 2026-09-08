"""Product creation HTTP boundary."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.product.api.schemas import ProductResponse
from erp.modules.product.application.commands import CommandMetadata, CreateProduct
from erp.modules.product.application.creation import ProductCreationService
from erp.modules.product.domain import ProductType
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/products", tags=["product-master"])


class CreateProductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    code: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    product_type: ProductType
    uom: str = Field(min_length=1, max_length=12)


class ProductCommandResponse(BaseModel):
    product: ProductResponse
    event_id: UUID | None
    audit_event_id: UUID | None
    idempotency_replayed: bool = False


def get_creation(request: Request) -> ProductCreationService:
    service = getattr(request.app.state, "product_creation", None)
    if not isinstance(service, ProductCreationService):
        raise ApplicationError(
            code="PRODUCT_COMMAND_UNAVAILABLE",
            message="Product commands unavailable.",
            status_code=503,
        )
    return service


def metadata(request: Request) -> CommandMetadata:
    return CommandMetadata(
        UUID(request.state.request_id),
        UUID(request.state.correlation_id),
        request.client.host if request.client is not None else None,
    )


@router.post("", status_code=201, response_model=ProductCommandResponse)
async def create_product(
    body: CreateProductRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[ProductCreationService, Depends(get_creation)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> ProductCommandResponse:
    command = CreateProduct(
        company_id=body.company_id,
        code=body.code,
        sku=body.sku,
        name=body.name,
        product_type=body.product_type,
        uom=body.uom,
        idempotency_key=idempotency_key,
        metadata=metadata(request),
    )
    result = await service.create(context, command)
    response.headers["Location"] = (
        f"/api/v1/products/{result.product.id}?company_id={result.product.company_id}"
    )
    response.headers["ETag"] = f'"{result.product.version}"'
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    response.headers["Cache-Control"] = "no-store"
    return ProductCommandResponse.model_validate(result.to_dict())


__all__ = ["ProductCommandResponse", "metadata", "router"]
