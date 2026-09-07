"""M2 tests use real PostgreSQL and clean up only their own fixture companies."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from erp.modules.admin.domain import Company, EconomicGroup
from erp.modules.admin.infrastructure import (
    CompanyModel,
    CompanyRepository,
    EconomicGroupModel,
    EconomicGroupRepository,
)
from erp.modules.product.domain import Product, ProductLifecycle, ProductType
from erp.modules.product.infrastructure import ProductModel, ProductRepository
from erp.platform.concurrency import OptimisticLockError
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.errors import ApplicationError

pytestmark = pytest.mark.integration


def _cnpj() -> str:
    value = f"12{uuid4().int % 10_000_000_000:010d}"
    for weights in ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)):
        remainder = (
            sum(int(digit) * weight for digit, weight in zip(value, weights, strict=True)) % 11
        )
        value += str(0 if remainder < 2 else 11 - remainder)
    return value


@dataclass(frozen=True)
class Fixture:
    database: Database
    company_id: UUID
    other_company_id: UUID
    actor_id: UUID

    def product(self, *, code: str = "TEST", other_company: bool = False) -> Product:
        return Product.create(
            company_id=self.other_company_id if other_company else self.company_id,
            code=code,
            sku=f"TEST-{uuid4().hex.upper()}",
            name="Product fixture",
            product_type=ProductType.PA,
            uom="UN",
        )


@asynccontextmanager
async def fixture() -> AsyncIterator[Fixture]:
    database = Database(get_settings())
    actor_id = uuid4()
    group = EconomicGroup.create(code=f"T{uuid4().hex[:20]}", name="M2 test fixture")
    companies = tuple(
        Company.create(
            group_id=group.id,
            code=f"T{uuid4().hex[:20]}",
            legal_name="M2 test company",
            trade_name=None,
            tax_id=_cnpj(),
            timezone="America/Sao_Paulo",
        )
        for _ in range(2)
    )
    company_ids = tuple(company.id for company in companies)
    try:
        async with database.session() as session, session.begin():
            await EconomicGroupRepository().add(session, group, actor_id=actor_id)
            for company in companies:
                await CompanyRepository().add(session, company, actor_id=actor_id)
        yield Fixture(database, companies[0].id, companies[1].id, actor_id)
    finally:
        try:
            async with database.session() as session, session.begin():
                await session.execute(
                    delete(ProductModel).where(ProductModel.company_id.in_(company_ids))
                )
                await session.execute(delete(CompanyModel).where(CompanyModel.id.in_(company_ids)))
                await session.execute(
                    delete(EconomicGroupModel).where(EconomicGroupModel.id == group.id)
                )
        finally:
            await database.dispose()


def test_product_round_trip_update_and_actor_metadata() -> None:
    async def scenario() -> None:
        async with fixture() as data:
            item = data.product()
            second_actor = uuid4()
            async with data.database.session() as session, session.begin():
                repository = ProductRepository(session, company_id=data.company_id)
                await repository.add(item, actor_id=data.actor_id)
                assert await repository.get(item.id) == item
                changed = item.update_details(name="Updated", uom="CX")
                assert await repository.save(changed, actor_id=second_actor) == changed
                assert await repository.get(item.id) == changed
            async with data.database.session() as session:
                model = await session.get(ProductModel, item.id)
                assert model is not None
                assert model.created_by == data.actor_id
                assert model.updated_by == second_actor
                assert model.updated_at >= model.created_at
                assert model.version == 2

    asyncio.run(scenario())


def test_get_and_list_are_company_scoped_even_with_known_foreign_id() -> None:
    async def scenario() -> None:
        async with fixture() as data, data.database.session() as session, session.begin():
            own = data.product()
            foreign = data.product(other_company=True)
            own_repo = ProductRepository(session, company_id=data.company_id)
            foreign_repo = ProductRepository(session, company_id=data.other_company_id)
            await own_repo.add(own, actor_id=data.actor_id)
            await foreign_repo.add(foreign, actor_id=data.actor_id)
            assert await own_repo.list() == (own,)
            assert await foreign_repo.list() == (foreign,)
            assert await own_repo.get(foreign.id) is None
            assert await own_repo.get(uuid4()) is None
            assert await ProductRepository(session, company_id=uuid4()).list() == ()

    asyncio.run(scenario())


def test_company_mismatch_rejects_add_and_save_before_writing() -> None:
    async def scenario() -> None:
        async with fixture() as data, data.database.session() as session, session.begin():
            foreign = data.product(other_company=True)
            repository = ProductRepository(session, company_id=data.company_id)
            with pytest.raises(ApplicationError, match="outside") as captured:
                await repository.add(foreign, actor_id=data.actor_id)
            assert captured.value.code == "SCOPE_FORBIDDEN"
            with pytest.raises(ApplicationError, match="outside"):
                await repository.save(
                    foreign.update_details(name="Attack", uom="UN"), actor_id=data.actor_id
                )
            assert await session.get(ProductModel, foreign.id) is None

    asyncio.run(scenario())


def test_forged_company_in_snapshot_cannot_update_foreign_row() -> None:
    async def scenario() -> None:
        async with fixture() as data, data.database.session() as session, session.begin():
            foreign = data.product(other_company=True)
            foreign_repo = ProductRepository(session, company_id=data.other_company_id)
            await foreign_repo.add(foreign, actor_id=data.actor_id)
            forged = replace(
                foreign.update_details(name="Attack", uom="UN"), company_id=data.company_id
            )
            with pytest.raises(OptimisticLockError):
                await ProductRepository(session, company_id=data.company_id).save(
                    forged, actor_id=data.actor_id
                )
            assert await foreign_repo.get(foreign.id) == foreign

    asyncio.run(scenario())


def test_list_pagination_and_lifecycle_filter() -> None:
    async def scenario() -> None:
        async with fixture() as data, data.database.session() as session, session.begin():
            repository = ProductRepository(session, company_id=data.company_id)
            for code in ("C", "A", "B"):
                item = data.product(code=code)
                await repository.add(item, actor_id=data.actor_id)
                if code == "B":
                    await repository.save(
                        replace(item, lifecycle=ProductLifecycle.EM_HOMOLOGACAO, version=2),
                        actor_id=data.actor_id,
                    )
            assert [item.code for item in await repository.list()] == ["A", "B", "C"]
            assert [item.code for item in await repository.list(limit=1, offset=1)] == ["B"]
            assert [
                item.code
                for item in await repository.list(lifecycle=ProductLifecycle.EM_DESENVOLVIMENTO)
            ] == ["A", "C"]
            assert await repository.list(offset=10) == ()

    asyncio.run(scenario())


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (101, 0), (True, 0), (1, -1), (1, True)])
def test_rejects_invalid_pagination(limit: int, offset: int) -> None:
    async def scenario() -> None:
        async with fixture() as data, data.database.session() as session:
            with pytest.raises(ValueError, match=r"limit|offset"):
                await ProductRepository(session, company_id=data.company_id).list(
                    limit=limit, offset=offset
                )

    asyncio.run(scenario())


def test_rejects_absent_context_and_invalid_initial_state() -> None:
    async def scenario() -> None:
        async with fixture() as data, data.database.session() as session:
            with pytest.raises(ValueError, match="company"):
                ProductRepository(session, company_id=None)  # type: ignore[arg-type]
            repository = ProductRepository(session, company_id=data.company_id)
            with pytest.raises(ValueError, match="actor"):
                await repository.add(data.product(), actor_id=None)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="version one"):
                await repository.add(replace(data.product(), version=2), actor_id=data.actor_id)
            with pytest.raises(ValueError, match="development"):
                await repository.add(
                    replace(data.product(), lifecycle=ProductLifecycle.ATIVO),
                    actor_id=data.actor_id,
                )
            with pytest.raises(ValueError, match="changed"):
                await repository.save(data.product(), actor_id=data.actor_id)
            with pytest.raises(ValueError, match="lifecycle"):
                await repository.list(lifecycle="INVALID")  # type: ignore[arg-type]

    asyncio.run(scenario())


def test_add_and_save_do_not_commit_the_callers_transaction() -> None:
    async def scenario() -> None:
        async with fixture() as data:
            item = data.product()
            async with data.database.session() as session:
                await ProductRepository(session, company_id=data.company_id).add(
                    item, actor_id=data.actor_id
                )
                await session.rollback()
            async with data.database.session() as session, session.begin():
                repository = ProductRepository(session, company_id=data.company_id)
                assert await repository.get(item.id) is None
                await repository.add(item, actor_id=data.actor_id)
            async with data.database.session() as session:
                await ProductRepository(session, company_id=data.company_id).save(
                    item.update_details(name="Rolled back", uom="UN"), actor_id=data.actor_id
                )
                await session.rollback()
            async with data.database.session() as session:
                assert (
                    await ProductRepository(session, company_id=data.company_id).get(item.id)
                    == item
                )

    asyncio.run(scenario())


def test_concurrent_sessions_have_exactly_one_version_winner() -> None:
    async def scenario() -> None:
        async with fixture() as data:
            item = data.product()
            async with data.database.session() as session, session.begin():
                await ProductRepository(session, company_id=data.company_id).add(
                    item, actor_id=data.actor_id
                )
            barrier = asyncio.Barrier(2)

            async def update_product(name: str) -> Product | OptimisticLockError:
                try:
                    async with data.database.session() as session, session.begin():
                        repository = ProductRepository(session, company_id=data.company_id)
                        snapshot = await repository.get(item.id)
                        assert snapshot is not None
                        await asyncio.wait_for(barrier.wait(), timeout=10)
                        return await repository.save(
                            snapshot.update_details(name=name, uom="UN"), actor_id=data.actor_id
                        )
                except OptimisticLockError as error:
                    return error

            results = await asyncio.wait_for(
                asyncio.gather(update_product("Winner A"), update_product("Winner B")), timeout=20
            )
            winners = [result for result in results if isinstance(result, Product)]
            conflicts = [result for result in results if isinstance(result, OptimisticLockError)]
            assert len(winners) == len(conflicts) == 1
            assert conflicts[0].code == "VERSION_CONFLICT"
            assert winners[0].version == 2
            async with data.database.session() as session:
                assert (
                    await ProductRepository(session, company_id=data.company_id).get(item.id)
                    == winners[0]
                )

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["code", "sku", "product_type"])
def test_business_keys_and_type_cannot_be_changed_by_save(field: str) -> None:
    async def scenario() -> None:
        async with fixture() as data, data.database.session() as session, session.begin():
            repository = ProductRepository(session, company_id=data.company_id)
            item = data.product()
            await repository.add(item, actor_id=data.actor_id)
            candidate = item.update_details(name="Changed", uom="UN")
            if field == "code":
                candidate = replace(candidate, code="DIFFERENT")
            elif field == "sku":
                candidate = replace(candidate, sku="DIFFERENT")
            else:
                candidate = replace(candidate, product_type=ProductType.KIT)
            with pytest.raises(OptimisticLockError):
                await repository.save(candidate, actor_id=data.actor_id)
            assert await repository.get(item.id) == item

    asyncio.run(scenario())


@pytest.mark.parametrize("global_sku", [True, False])
def test_duplicate_business_keys_have_stable_conflict(global_sku: bool) -> None:
    async def scenario() -> None:
        async with fixture() as data, data.database.session() as session, session.begin():
            first = data.product()
            await ProductRepository(session, company_id=first.company_id).add(
                first, actor_id=data.actor_id
            )
            second = data.product(other_company=global_sku)
            if global_sku:
                second = replace(second, sku=first.sku)
            async with session.begin_nested() as savepoint:
                with pytest.raises(ApplicationError) as captured:
                    await ProductRepository(session, company_id=second.company_id).add(
                        second, actor_id=data.actor_id
                    )
                assert captured.value.code == "PRODUCT_IDENTIFIER_CONFLICT"
                assert captured.value.status_code == 409
                await savepoint.rollback()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code", "lower"),
        ("sku", "bad sku"),
        ("name", " "),
        ("uom", "lower"),
        ("product_type", "BAD"),
        ("lifecycle", "INVALID"),
        ("version", 0),
        ("company_id", uuid4()),
        ("company_id", None),
        ("created_by", None),
    ],
)
def test_database_rejects_invalid_values(field: str, value: object) -> None:
    async def scenario() -> None:
        async with fixture() as data, data.database.session() as session, session.begin():
            item = data.product()
            await ProductRepository(session, company_id=data.company_id).add(
                item, actor_id=data.actor_id
            )
            async with session.begin_nested() as savepoint:
                with pytest.raises(IntegrityError):
                    await session.execute(
                        update(ProductModel)
                        .where(ProductModel.id == item.id)
                        .values({field: value})
                    )
                await savepoint.rollback()

    asyncio.run(scenario())


def test_missing_foundation_company_fails_without_product_insert() -> None:
    async def scenario() -> None:
        async with fixture() as data, data.database.session() as session:
            item = replace(data.product(), company_id=uuid4())
            with pytest.raises(IntegrityError):
                await ProductRepository(session, company_id=item.company_id).add(
                    item, actor_id=data.actor_id
                )
            await session.rollback()
            assert (
                await session.scalar(select(ProductModel.id).where(ProductModel.id == item.id))
                is None
            )

    asyncio.run(scenario())
