"""Tenant-bound persistence for complete bill-of-materials aggregates."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.production.domain import (
    BillOfMaterials,
    BomItem,
    EngineeringVersion,
    ProductionConflictError,
    ProductionQuantity,
    ProductionScopeError,
    ProductionVersionConflictError,
    ScrapRate,
    UnitOfMeasure,
)
from erp.modules.production.infrastructure.engineering_model import (
    BomComponentModel,
    BomHeaderModel,
)


def _bom(
    header: BomHeaderModel,
    components: tuple[BomComponentModel, ...],
) -> BillOfMaterials:
    return BillOfMaterials(
        company_id=header.company_id,
        product_id=header.product_id,
        version=EngineeringVersion(
            code=header.version_code,
            revision=header.engineering_revision,
            effective_from=header.effective_from,
            effective_until=header.effective_until,
        ),
        output_quantity=ProductionQuantity(
            header.output_quantity,
            UnitOfMeasure(header.output_uom),
        ),
        items=tuple(
            BomItem(
                component_product_id=component.component_product_id,
                quantity_per_output=ProductionQuantity(
                    component.quantity_per_output,
                    UnitOfMeasure(component.uom),
                ),
                scrap_rate=ScrapRate(component.scrap_rate),
            )
            for component in components
        ),
        record_version=header.version,
    )


class BOMRepository:
    """Persist BOM headers and lines without owning the transaction boundary."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, aggregate: BillOfMaterials, *, actor_id: UUID) -> BillOfMaterials:
        self._validate_write(aggregate, actor_id)
        if aggregate.record_version != 1:
            raise ValueError("A new BOM must start at record_version one.")
        header_id = uuid4()
        self._session.add(
            BomHeaderModel(
                id=header_id,
                company_id=self._company_id,
                product_id=aggregate.product_id,
                version_code=aggregate.version.code,
                engineering_revision=aggregate.version.revision,
                effective_from=aggregate.version.effective_from,
                effective_until=aggregate.version.effective_until,
                output_quantity=aggregate.output_quantity.amount,
                output_uom=aggregate.output_quantity.unit,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_conflict()
        self._add_components(header_id, aggregate.items)
        await self._flush_conflict()
        return aggregate

    async def get(self, product_id: UUID, version_code: str) -> BillOfMaterials | None:
        code = self._version_code(version_code)
        result = await self._session.scalars(
            select(BomHeaderModel)
            .where(
                BomHeaderModel.company_id == self._company_id,
                BomHeaderModel.product_id == product_id,
                BomHeaderModel.version_code == code,
            )
            .execution_options(populate_existing=True)
        )
        header = result.one_or_none()
        if header is None:
            return None
        return _bom(header, await self._components(header.id))

    async def save(
        self,
        aggregate: BillOfMaterials,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> BillOfMaterials:
        self._validate_write(aggregate, actor_id)
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected_version must be a positive integer.")
        if aggregate.record_version != expected_version + 1:
            raise ValueError("save requires exactly one new record version.")
        result = await self._session.execute(
            update(BomHeaderModel)
            .where(
                BomHeaderModel.company_id == self._company_id,
                BomHeaderModel.product_id == aggregate.product_id,
                BomHeaderModel.version_code == aggregate.version.code,
                BomHeaderModel.version == expected_version,
            )
            .values(
                engineering_revision=aggregate.version.revision,
                effective_from=aggregate.version.effective_from,
                effective_until=aggregate.version.effective_until,
                output_quantity=aggregate.output_quantity.amount,
                output_uom=aggregate.output_quantity.unit,
                version=aggregate.record_version,
                updated_at=datetime.now(UTC),
                updated_by=actor_id,
            )
            .returning(BomHeaderModel.id)
            .execution_options(synchronize_session=False)
        )
        header_id = result.scalar_one_or_none()
        if header_id is None:
            raise ProductionVersionConflictError(expected_version)
        await self._session.execute(
            delete(BomComponentModel).where(
                BomComponentModel.company_id == self._company_id,
                BomComponentModel.bom_id == header_id,
            )
        )
        self._add_components(header_id, aggregate.items)
        await self._flush_conflict()
        return aggregate

    async def _components(self, header_id: UUID) -> tuple[BomComponentModel, ...]:
        result = await self._session.scalars(
            select(BomComponentModel)
            .where(
                BomComponentModel.company_id == self._company_id,
                BomComponentModel.bom_id == header_id,
            )
            .order_by(BomComponentModel.sequence)
            .execution_options(populate_existing=True)
        )
        return tuple(result)

    def _add_components(self, header_id: UUID, items: tuple[BomItem, ...]) -> None:
        self._session.add_all(
            [
                BomComponentModel(
                    id=uuid4(),
                    company_id=self._company_id,
                    bom_id=header_id,
                    sequence=sequence,
                    component_product_id=item.component_product_id,
                    quantity_per_output=item.quantity_per_output.amount,
                    uom=item.quantity_per_output.unit,
                    scrap_rate=item.scrap_rate.value,
                    version=1,
                )
                for sequence, item in enumerate(items, start=1)
            ]
        )

    def _validate_write(self, aggregate: BillOfMaterials, actor_id: UUID) -> None:
        if not isinstance(aggregate, BillOfMaterials):
            raise TypeError("aggregate must be a BillOfMaterials.")
        if aggregate.company_id != self._company_id:
            raise ProductionScopeError("BOM belongs to another company.")
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise ValueError("actor_id must be a non-zero UUID.")

    @staticmethod
    def _version_code(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("version_code must be non-empty text.")
        return value.strip().upper()

    async def _flush_conflict(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) in {"23503", "23505", "23514"}:
                raise ProductionConflictError(
                    "BOM conflicts with a product, version or tenant constraint."
                ) from error
            raise


__all__ = ["BOMRepository", "_bom"]

