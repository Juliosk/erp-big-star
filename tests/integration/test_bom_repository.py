"""Production engineering persistence against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, delete, inspect

from erp.modules.product.domain import Product
from erp.modules.product.infrastructure import ProductRepository
from erp.modules.production.domain import (
    BillOfMaterials,
    BomExpansionService,
    BomItem,
    EngineeringVersion,
    ProductionConflictError,
    ProductionQuantity,
    ProductionRouting,
    ProductionScopeError,
    ProductionVersionConflictError,
    RoutingOperation,
    ScrapRate,
    UnitOfMeasure,
    WorkCenter,
    WorkCenterCode,
    WorkCenterConstraint,
)
from erp.modules.production.infrastructure import (
    BomComponentModel,
    BomHeaderModel,
    BOMRepository,
    RoutingHeaderModel,
    RoutingOperationModel,
    RoutingRepository,
    WorkCenterModel,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from tests.integration.test_product_persistence import Fixture, fixture

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class ProductionFixture:
    data: Fixture
    finished: Product
    subassembly: Product
    raw_material: Product
    foreign_material: Product

    @property
    def company_id(self) -> UUID:
        return self.data.company_id

    @property
    def other_company_id(self) -> UUID:
        return self.data.other_company_id

    @property
    def actor_id(self) -> UUID:
        return self.data.actor_id

    @property
    def database(self) -> Database:
        return self.data.database


@asynccontextmanager
async def production_fixture() -> AsyncIterator[ProductionFixture]:
    async with fixture() as data:
        finished = data.product(code=f"FIN-{uuid4().hex[:8].upper()}")
        subassembly = data.product(code=f"SUB-{uuid4().hex[:8].upper()}")
        raw_material = data.product(code=f"RAW-{uuid4().hex[:8].upper()}")
        foreign_material = data.product(
            code=f"FOR-{uuid4().hex[:8].upper()}", other_company=True
        )
        async with data.database.session() as session, session.begin():
            own = ProductRepository(session, company_id=data.company_id)
            await own.add(finished, actor_id=data.actor_id)
            await own.add(subassembly, actor_id=data.actor_id)
            await own.add(raw_material, actor_id=data.actor_id)
            await ProductRepository(session, company_id=data.other_company_id).add(
                foreign_material, actor_id=data.actor_id
            )
        production = ProductionFixture(
            data,
            finished,
            subassembly,
            raw_material,
            foreign_material,
        )
        company_ids = (data.company_id, data.other_company_id)
        try:
            yield production
        finally:
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(RoutingOperationModel).where(
                        RoutingOperationModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(RoutingHeaderModel).where(
                        RoutingHeaderModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(BomComponentModel).where(
                        BomComponentModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(BomHeaderModel).where(BomHeaderModel.company_id.in_(company_ids))
                )
                await session.execute(
                    delete(WorkCenterModel).where(
                        WorkCenterModel.company_id.in_(company_ids)
                    )
                )


def _version(code: str = "R1") -> EngineeringVersion:
    return EngineeringVersion(code, 1, date(2026, 11, 4))


def _quantity(value: str, unit: UnitOfMeasure = UnitOfMeasure.EACH) -> ProductionQuantity:
    return ProductionQuantity(Decimal(value), unit)


def _bom(
    data: ProductionFixture,
    product_id: UUID,
    *items: BomItem,
    record_version: int = 1,
) -> BillOfMaterials:
    return BillOfMaterials(
        company_id=data.company_id,
        product_id=product_id,
        version=_version(),
        output_quantity=_quantity("1"),
        items=items,
        record_version=record_version,
    )


def _item(product_id: UUID, value: str, *, scrap: str = "0") -> BomItem:
    return BomItem(
        product_id,
        _quantity(value),
        ScrapRate(Decimal(scrap)),
    )


def _routing(data: ProductionFixture, *, record_version: int = 1) -> ProductionRouting:
    constraint = WorkCenterConstraint(
        data.company_id,
        (WorkCenterCode("CUT-01"),),
        frozenset({"LASER"}),
    )
    return ProductionRouting(
        company_id=data.company_id,
        product_id=data.finished.id,
        version=_version(),
        operations=(
            RoutingOperation(
                sequence=10,
                name="Precision cutting",
                work_center=constraint,
                setup_minutes=Decimal("5"),
                run_minutes_per_unit=Decimal("0.5"),
            ),
        ),
        record_version=record_version,
    )


def test_multilevel_bom_and_routing_round_trip() -> None:
    async def scenario() -> None:
        async with production_fixture() as data:
            subassembly = _bom(
                data,
                data.subassembly.id,
                _item(data.raw_material.id, "3", scrap="0.10"),
            )
            finished = _bom(
                data,
                data.finished.id,
                _item(data.subassembly.id, "2"),
                _item(data.raw_material.id, "1"),
            )
            center = WorkCenter(
                data.company_id,
                WorkCenterCode("CUT-01"),
                frozenset({"LASER", "PRECISION"}),
            )
            routing = _routing(data)
            async with data.database.session() as session, session.begin():
                bom_repository = BOMRepository(session, company_id=data.company_id)
                routing_repository = RoutingRepository(session, company_id=data.company_id)
                await bom_repository.add(subassembly, actor_id=data.actor_id)
                await bom_repository.add(finished, actor_id=data.actor_id)
                await routing_repository.add_work_center(center, actor_id=data.actor_id)
                await routing_repository.add(routing, actor_id=data.actor_id)

                loaded_finished = await bom_repository.get(data.finished.id, "r1")
                loaded_subassembly = await bom_repository.get(data.subassembly.id, "R1")
                assert loaded_finished == finished
                assert loaded_subassembly == subassembly
                assert await routing_repository.get(data.finished.id, "r1") == routing
                assert await routing_repository.get_work_center(WorkCenterCode("CUT-01")) == center

                assert loaded_finished is not None
                assert loaded_subassembly is not None
                requirements = BomExpansionService(
                    data.company_id, (loaded_finished, loaded_subassembly)
                ).expand(data.finished.id, _quantity("1"))
                assert len(requirements) == 1
                assert requirements[0].product_id == data.raw_material.id
                assert requirements[0].quantity == _quantity("7.666667")

    asyncio.run(scenario())


def test_optimistic_updates_have_one_winner() -> None:
    async def scenario() -> None:
        async with production_fixture() as data:
            original = _bom(data, data.finished.id, _item(data.raw_material.id, "1"))
            center = WorkCenter(
                data.company_id,
                WorkCenterCode("CUT-01"),
                frozenset({"LASER"}),
            )
            routing = _routing(data)
            async with data.database.session() as session, session.begin():
                bom_repository = BOMRepository(session, company_id=data.company_id)
                routing_repository = RoutingRepository(session, company_id=data.company_id)
                await bom_repository.add(original, actor_id=data.actor_id)
                await routing_repository.add_work_center(center, actor_id=data.actor_id)
                await routing_repository.add(routing, actor_id=data.actor_id)

                changed = replace(
                    original,
                    items=(_item(data.raw_material.id, "2"),),
                    record_version=2,
                )
                assert await bom_repository.save(
                    changed, actor_id=data.actor_id, expected_version=1
                ) == changed
                with pytest.raises(ProductionVersionConflictError) as captured:
                    await bom_repository.save(
                        changed, actor_id=data.actor_id, expected_version=1
                    )
                assert captured.value.code == "VERSION_CONFLICT"

                changed_routing = replace(routing, record_version=2)
                await routing_repository.save(
                    changed_routing, actor_id=data.actor_id, expected_version=1
                )
                changed_center = replace(
                    center,
                    capabilities=frozenset({"LASER", "CNC"}),
                    record_version=2,
                )
                await routing_repository.save_work_center(
                    changed_center, actor_id=data.actor_id, expected_version=1
                )
                assert await routing_repository.get_work_center(center.code) == changed_center

    asyncio.run(scenario())


def test_tenant_scope_and_composite_product_foreign_keys() -> None:
    async def scenario() -> None:
        async with production_fixture() as data:
            own = _bom(data, data.finished.id, _item(data.raw_material.id, "1"))
            invalid_reference = _bom(
                data,
                data.subassembly.id,
                _item(data.foreign_material.id, "1"),
            )
            async with data.database.session() as session, session.begin():
                repository = BOMRepository(session, company_id=data.company_id)
                await repository.add(own, actor_id=data.actor_id)
                assert (
                    await BOMRepository(
                        session, company_id=data.other_company_id
                    ).get(data.finished.id, "R1")
                    is None
                )
                with pytest.raises(ProductionScopeError):
                    await BOMRepository(
                        session, company_id=data.other_company_id
                    ).add(own, actor_id=data.actor_id)
                nested = await session.begin_nested()
                with pytest.raises(ProductionConflictError):
                    await repository.add(invalid_reference, actor_id=data.actor_id)
                await nested.rollback()

    asyncio.run(scenario())


def test_repository_never_commits_caller_transaction() -> None:
    async def scenario() -> None:
        async with production_fixture() as data:
            aggregate = _bom(data, data.finished.id, _item(data.raw_material.id, "1"))
            async with data.database.session() as session:
                transaction = await session.begin()
                await BOMRepository(session, company_id=data.company_id).add(
                    aggregate, actor_id=data.actor_id
                )
                await transaction.rollback()
            async with data.database.session() as session:
                assert (
                    await BOMRepository(session, company_id=data.company_id).get(
                        data.finished.id, "R1"
                    )
                    is None
                )

    asyncio.run(scenario())


def test_migration_0051_is_reversible_on_postgresql() -> None:
    configuration = Config("alembic.ini")

    async def verify(expected: bool) -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:

                def inspect_schema(sync_connection: Connection) -> None:
                    inspector = inspect(sync_connection)
                    tables = set(inspector.get_table_names(schema="production"))
                    expected_tables = {
                        "bom_header",
                        "bom_component",
                        "routing_header",
                        "routing_operation",
                        "work_center",
                    }
                    assert expected_tables.issubset(tables) is expected
                    if not expected:
                        return
                    foreign_keys = inspector.get_foreign_keys(
                        "bom_component", schema="production"
                    )
                    assert any(
                        key["constrained_columns"] == ["company_id", "bom_id"]
                        for key in foreign_keys
                    )
                    indexes = {
                        value["name"]
                        for value in inspector.get_indexes(
                            "bom_component", schema="production"
                        )
                    }
                    assert "ix_bom_component_company_product" in indexes

                await connection.run_sync(inspect_schema)
        finally:
            await database.dispose()

    try:
        command.downgrade(configuration, "0050")
        asyncio.run(verify(False))
        command.upgrade(configuration, "0051")
        asyncio.run(verify(True))
    finally:
        command.upgrade(configuration, "head")


__all__: list[str] = []

