"""Session-owning read adapter; all queries delegate to the tenant-bound repository."""

from uuid import UUID

from erp.modules.product.application.queries import ProductPage
from erp.modules.product.domain import Product, ProductLifecycle
from erp.modules.product.infrastructure.product_repository import ProductRepository
from erp.platform.database import Database


class PostgresProductDirectory:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        lifecycle: ProductLifecycle | None,
    ) -> ProductPage:
        async with self._database.session() as session:
            repository = ProductRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list(limit=page_size, offset=offset, lifecycle=lifecycle)
            more = await repository.list(limit=1, offset=offset + page_size, lifecycle=lifecycle)
            return ProductPage(items, page, page_size, bool(more))

    async def get(self, company_id: UUID, product_id: UUID) -> Product | None:
        async with self._database.session() as session:
            return await ProductRepository(session, company_id=company_id).get(product_id)


__all__ = ["PostgresProductDirectory"]
