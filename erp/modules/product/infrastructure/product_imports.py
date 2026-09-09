"""M2 adapter participates in a composed transaction; never commits it per row."""

from dataclasses import replace
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.admin.contracts import SecurityContext
from erp.modules.product.application.commands import CommandMetadata, product_snapshot
from erp.modules.product.application.permissions import (
    PRODUCT_CREATE,
    PRODUCT_READ,
    PRODUCT_UPDATE,
    ProductAuthorization,
)
from erp.modules.product.contracts import ProductImportPlan, ProductImportRow
from erp.modules.product.domain import Product, ProductType
from erp.modules.product.infrastructure.product_effects import ProductEffects
from erp.modules.product.infrastructure.product_model import ProductModel
from erp.modules.product.infrastructure.product_repository import ProductRepository, _product
from erp.platform.errors import ApplicationError


class PostgresProductImports:
    def __init__(
        self,
        session: AsyncSession,
        company_id: UUID,
        context: SecurityContext,
        authorization: ProductAuthorization,
        metadata: CommandMetadata,
    ) -> None:
        self._session = session
        self._company = company_id
        self._context = context
        self._authorization = authorization
        self._metadata = metadata
        self._repository = ProductRepository(session, company_id=company_id)

    async def authorize(self, plans: tuple[ProductImportPlan, ...]) -> None:
        await self._authorization.require(self._context, self._company, PRODUCT_READ)
        for action in {plan.action for plan in plans}:
            await self._authorization.require(
                self._context,
                self._company,
                PRODUCT_CREATE if action == "CREATE" else PRODUCT_UPDATE,
                write=True,
            )

    async def validate(self, rows: tuple[ProductImportRow, ...]) -> tuple[ProductImportPlan, ...]:
        await self._authorization.require(self._context, self._company, PRODUCT_READ)
        plans = []
        seen_skus: set[str] = set()
        seen_codes: set[str] = set()
        for row in rows:
            values = dict(row.values)
            for field in ("code", "sku", "product_type", "uom"):
                values[field] = values.get(field, "").strip().upper()
            errors = list(row.errors)
            sku, code = values["sku"], values["code"]
            if sku in seen_skus or (code and code in seen_codes):
                errors.append("DUPLICATE_FILE_IDENTIFIER")
            seen_skus.add(sku)
            seen_codes.add(code)
            model = await self._session.scalar(
                select(ProductModel)
                .where(ProductModel.company_id == self._company, ProductModel.sku == sku)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            before = None if model is None else _product(model)
            await self._authorization.require(
                self._context,
                self._company,
                PRODUCT_CREATE if before is None else PRODUCT_UPDATE,
                write=True,
            )
            proposed = dict(values)
            differences: tuple[str, ...] = ()
            try:
                if before is None:
                    product = Product.create(
                        company_id=self._company,
                        code=code,
                        sku=sku,
                        name=values.get("name", ""),
                        product_type=ProductType(values["product_type"]),
                        uom=values["uom"],
                    )
                    collision = await self._session.scalar(
                        select(ProductModel.id)
                        .where(
                            or_(
                                ProductModel.sku == sku,
                                (ProductModel.company_id == self._company)
                                & (ProductModel.code == code),
                            )
                        )
                        .limit(1)
                    )
                    if collision is not None:
                        errors.append("PRODUCT_IDENTIFIER_CONFLICT")
                    differences = ("code", "sku", "name", "product_type", "uom")
                else:
                    if (code and code != before.code) or (
                        values["product_type"] and values["product_type"] != before.product_type
                    ):
                        errors.append("IMMUTABLE_PRODUCT_IDENTITY")
                    product = before.update_details(name=values.get("name", ""), uom=values["uom"])
                    differences = tuple(
                        field
                        for field in ("name", "uom")
                        if getattr(before, field) != getattr(product, field)
                    )
                proposed = {
                    key: str(getattr(product, key))
                    for key in ("code", "sku", "name", "product_type", "uom")
                }
            except ValueError:
                errors.append("INVALID_PRODUCT_FIELDS")
            plans.append(
                ProductImportPlan(
                    row.number,
                    "CREATE" if before is None else "UPDATE" if differences else "UNCHANGED",
                    None if before is None else product_snapshot(before),
                    proposed,
                    differences,
                    tuple(errors),
                )
            )
        return tuple(plans)

    async def commit(self, plans: tuple[ProductImportPlan, ...]) -> int:
        # Revalidate under the same transaction, including scopes, unique keys and versions.
        fresh = await self.validate(
            tuple(ProductImportRow(plan.number, plan.proposed) for plan in plans)
        )
        if any(plan.errors for plan in fresh) or fresh != plans:
            raise ApplicationError(
                code="IMPORT_PREVIEW_STALE",
                message="Product data changed. Validate a new preview.",
                status_code=409,
            )
        count = 0
        actor = self._context.principal.user_id
        for plan in fresh:
            values = plan.proposed
            if plan.action == "UNCHANGED":
                continue
            before = None
            if plan.current is None:
                product = Product.create(
                    company_id=self._company,
                    code=values["code"],
                    sku=values["sku"],
                    name=values["name"],
                    product_type=ProductType(values["product_type"]),
                    uom=values["uom"],
                )
                await self._repository.add(product, actor_id=actor)
                event = "ProductCreated"
            else:
                before = await self._repository.get(UUID(plan.current["id"]))
                if before is None:
                    raise ApplicationError(
                        code="IMPORT_PREVIEW_STALE", message="Product missing.", status_code=409
                    )
                product = replace(
                    before,
                    name=values["name"],
                    uom=values["uom"],
                    version=int(plan.current["version"]) + 1,
                )
                product = await self._repository.save(product, actor_id=actor)
                event = "ProductUpdated"
            await ProductEffects().record(
                self._session,
                product,
                actor_id=actor,
                metadata=self._metadata,
                event_type=event,
                before=before,
                payload={
                    "product_id": str(product.id),
                    "sku": product.sku,
                    "product_type": product.product_type,
                    "version": product.version,
                    "changed_fields": list(plan.differences),
                },
            )
            count += 1
        return count


__all__ = ["PostgresProductImports"]
