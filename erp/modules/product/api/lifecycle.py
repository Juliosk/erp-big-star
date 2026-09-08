"""Lifecycle routes share mandatory version and idempotency contracts."""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.product.api.creation import ProductCommandResponse, metadata
from erp.modules.product.api.versioning import require_version
from erp.modules.product.application.lifecycle import ProductLifecycleService, TransitionProduct
from erp.modules.product.domain import ProductLifecycle
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/products", tags=["product-master"])


def get_lifecycle(request: Request) -> ProductLifecycleService:
    service = getattr(request.app.state, "product_lifecycle", None)
    if not isinstance(service, ProductLifecycleService):
        raise ApplicationError(
            code="PRODUCT_COMMAND_UNAVAILABLE",
            message="Product commands unavailable.",
            status_code=503,
        )
    return service


def _endpoint(target: ProductLifecycle) -> Callable[..., Awaitable[ProductCommandResponse]]:
    async def transition(
        product_id: UUID,
        company_id: UUID,
        request: Request,
        response: Response,
        context: Annotated[SecurityContext, Depends(resolve_security_context)],
        service: Annotated[ProductLifecycleService, Depends(get_lifecycle)],
        version: Annotated[int, Depends(require_version)],
        key: Annotated[str, Depends(require_idempotency_key)],
    ) -> ProductCommandResponse:
        result = await service.transition(
            context,
            TransitionProduct(company_id, product_id, target, version, key, metadata(request)),
        )
        response.headers["ETag"] = f'"{result.product.version}"'
        response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
        response.headers["Cache-Control"] = "no-store"
        return ProductCommandResponse.model_validate(result.to_dict())

    return transition


for path, target in (
    ("submit-for-homologation", ProductLifecycle.EM_HOMOLOGACAO),
    ("activate", ProductLifecycle.ATIVO),
    ("discontinue", ProductLifecycle.FORA_DE_LINHA),
):
    router.add_api_route(
        f"/{{product_id}}/{path}",
        _endpoint(target),
        methods=["POST"],
        response_model=ProductCommandResponse,
        name=f"product-{path}",
    )

__all__ = ["router"]
