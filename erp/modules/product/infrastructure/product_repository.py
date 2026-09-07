"""Tenant-bound persistence; transactions and authorization belong to the caller."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.product.domain import Product, ProductLifecycle, ProductType
from erp.modules.product.infrastructure.product_model import ProductModel
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


def _product(model: ProductModel) -> Product:
    return Product(
        id=model.id,
        company_id=model.company_id,
        code=model.code,
        sku=model.sku,
        name=model.name,
        product_type=ProductType(model.product_type),
        uom=model.uom,
        lifecycle=ProductLifecycle(model.lifecycle),
        version=model.version,
    )


class ProductRepository:
    """One previously authorized company per instance, with no unscoped operations."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, product: Product, *, actor_id: UUID) -> None:
        """Flush a new development product; never commit or publish an event."""
        self._validate_write(product, actor_id)
        if product.version != 1 or product.lifecycle is not ProductLifecycle.EM_DESENVOLVIMENTO:
            raise ValueError("A new product must start in development at version one.")
        self._session.add(
            ProductModel(
                id=product.id,
                company_id=self._company_id,
                code=product.code,
                sku=product.sku,
                name=product.name,
                product_type=product.product_type,
                uom=product.uom,
                lifecycle=product.lifecycle,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code="PRODUCT_IDENTIFIER_CONFLICT",
                    message="A product identifier is in use.",
                    status_code=409,
                ) from error
            raise

    async def get(self, product_id: UUID) -> Product | None:
        """Return no data for missing products or another company's product."""
        result = await self._session.scalars(
            select(ProductModel)
            .where(
                ProductModel.company_id == self._company_id,
                ProductModel.id == product_id,
            )
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _product(model)

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        lifecycle: ProductLifecycle | None = None,
    ) -> tuple[Product, ...]:
        """Bounded, deterministic company directory; no cross-company consolidation."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100.")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer.")
        if lifecycle is not None and not isinstance(lifecycle, ProductLifecycle):
            raise ValueError("lifecycle must be an official M2 state.")
        statement = select(ProductModel).where(ProductModel.company_id == self._company_id)
        if lifecycle is not None:
            statement = statement.where(ProductModel.lifecycle == lifecycle)
        result = await self._session.scalars(
            statement.order_by(ProductModel.code, ProductModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_product(model) for model in result)

    async def save(self, product: Product, *, actor_id: UUID) -> Product:
        """Compare and increment in one SQL statement, including the tenant predicate."""
        self._validate_write(product, actor_id)
        expected_version = product.version - 1
        if expected_version < 1:
            raise ValueError("save requires a changed aggregate version.")
        result = await self._session.scalars(
            update(ProductModel)
            .where(
                ProductModel.company_id == self._company_id,
                ProductModel.id == product.id,
                ProductModel.version == expected_version,
                ProductModel.code == product.code,
                ProductModel.sku == product.sku,
                ProductModel.product_type == product.product_type,
            )
            .values(
                name=product.name,
                uom=product.uom,
                lifecycle=product.lifecycle,
                version=product.version,
                updated_by=actor_id,
                updated_at=datetime.now(UTC),
            )
            .returning(ProductModel)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        model = result.one_or_none()
        if model is None:
            raise OptimisticLockError(expected_version=expected_version)
        return _product(model)

    def _validate_write(self, product: Product, actor_id: UUID) -> None:
        if product.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The product is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")


__all__ = ["ProductRepository"]
