"""PATCH changes details only; identity, scope and lifecycle are not mass-assignable."""

from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.product.api.creation import ProductCommandResponse, metadata
from erp.modules.product.api.versioning import require_version
from erp.modules.product.application.updates import ProductUpdateService, UpdateProduct
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/products", tags=["product-master"])


class UpdateProductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    uom: str | None = Field(default=None, min_length=1, max_length=12)

    @model_validator(mode="after")
    def reject_explicit_null(self) -> Self:
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Product fields cannot be null.")
        return self


def get_updates(request: Request) -> ProductUpdateService:
    service = getattr(request.app.state, "product_updates", None)
    if not isinstance(service, ProductUpdateService):
        raise ApplicationError(
            code="PRODUCT_COMMAND_UNAVAILABLE",
            message="Product commands unavailable.",
            status_code=503,
        )
    return service


@router.patch("/{product_id}", response_model=ProductCommandResponse)
async def update_product(
    product_id: UUID,
    company_id: UUID,
    body: UpdateProductRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[ProductUpdateService, Depends(get_updates)],
    version: Annotated[int, Depends(require_version)],
) -> ProductCommandResponse:
    result = await service.update(
        context,
        UpdateProduct(
            company_id=company_id,
            product_id=product_id,
            expected_version=version,
            metadata=metadata(request),
            name=body.name,
            uom=body.uom,
        ),
    )
    response.headers["ETag"] = f'"{result.product.version}"'
    response.headers["Cache-Control"] = "no-store"
    return ProductCommandResponse.model_validate(result.to_dict())


__all__ = ["router"]
