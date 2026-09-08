"""Authorized product creation orchestrates a single atomic persistence port."""

from erp.modules.admin.contracts import SecurityContext
from erp.modules.product.application.commands import (
    CreateProduct,
    ProductCommandResult,
    ProductCreationStore,
)
from erp.modules.product.application.permissions import PRODUCT_CREATE, ProductAuthorization
from erp.modules.product.domain import Product
from erp.platform.errors import ApplicationError, ErrorDetail


class ProductCreationService:
    def __init__(self, store: ProductCreationStore, authorization: ProductAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create(
        self, context: SecurityContext, command: CreateProduct
    ) -> ProductCommandResult:
        await self._authorization.require(context, command.company_id, PRODUCT_CREATE, write=True)
        try:
            product = Product.create(
                company_id=command.company_id,
                code=command.code,
                sku=command.sku,
                name=command.name,
                product_type=command.product_type,
                uom=command.uom,
            )
        except ValueError as error:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Invalid product data.",
                status_code=422,
                details=[ErrorDetail(message=str(error))],
            ) from error
        return await self._store.create(product, command, context.principal.user_id)


__all__ = ["ProductCreationService"]
