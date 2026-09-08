"""Authorized, versioned changes to mutable product details."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.product.application.commands import CommandMetadata, ProductCommandResult
from erp.modules.product.application.permissions import PRODUCT_UPDATE, ProductAuthorization
from erp.modules.product.domain import Product
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class UpdateProduct:
    company_id: UUID
    product_id: UUID
    expected_version: int
    metadata: CommandMetadata
    name: str | None = None
    uom: str | None = None


def apply_details(product: Product, command: UpdateProduct) -> Product:
    if product.version != command.expected_version:
        raise ApplicationError(
            code="VERSION_CONFLICT",
            message="The resource was changed by another transaction.",
            status_code=409,
        )
    if command.name is None and command.uom is None:
        raise ApplicationError(
            code="EMPTY_PATCH", message="At least one mutable field is required.", status_code=422
        )
    try:
        return product.update_details(
            name=product.name if command.name is None else command.name,
            uom=product.uom if command.uom is None else command.uom,
        )
    except ValueError as error:
        raise ApplicationError(
            code="BUSINESS_VALIDATION_ERROR",
            message="Invalid product data.",
            status_code=422,
            details=[ErrorDetail(message=str(error))],
        ) from error


class ProductUpdateStore(Protocol):
    async def update(self, command: UpdateProduct, actor_id: UUID) -> ProductCommandResult: ...


class ProductUpdateService:
    def __init__(self, store: ProductUpdateStore, authorization: ProductAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def update(
        self, context: SecurityContext, command: UpdateProduct
    ) -> ProductCommandResult:
        await self._authorization.require(context, command.company_id, PRODUCT_UPDATE, write=True)
        return await self._store.update(command, context.principal.user_id)


__all__ = ["ProductUpdateService", "ProductUpdateStore", "UpdateProduct", "apply_details"]
