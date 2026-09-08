"""Paginated M2 queries; authorization precedes any product read."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.product.application.permissions import PRODUCT_READ, ProductAuthorization
from erp.modules.product.domain import Product, ProductLifecycle
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class ProductPage:
    items: tuple[Product, ...]
    page: int
    page_size: int
    has_more: bool


class ProductDirectory(Protocol):
    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        lifecycle: ProductLifecycle | None,
    ) -> ProductPage: ...

    async def get(self, company_id: UUID, product_id: UUID) -> Product | None: ...


class ProductQueries:
    def __init__(self, directory: ProductDirectory, authorization: ProductAuthorization) -> None:
        self._directory = directory
        self._authorization = authorization

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        lifecycle: ProductLifecycle | None = None,
    ) -> ProductPage:
        await self._authorization.require(context, company_id, PRODUCT_READ)
        if not 1 <= page <= 100_000 or not 1 <= page_size <= 100:
            raise ApplicationError(
                code="VALIDATION_ERROR", message="Invalid pagination.", status_code=422
            )
        return await self._directory.list(
            company_id, page=page, page_size=page_size, lifecycle=lifecycle
        )

    async def get(self, context: SecurityContext, company_id: UUID, product_id: UUID) -> Product:
        await self._authorization.require(context, company_id, PRODUCT_READ)
        product = await self._directory.get(company_id, product_id)
        if product is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Product not found.", status_code=404
            )
        return product


__all__ = ["ProductDirectory", "ProductPage", "ProductQueries"]
