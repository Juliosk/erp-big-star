"""M14 tests use real PostgreSQL and clean up only their own fixture companies."""

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
from erp.modules.customer.domain import Customer, CustomerStatus, CustomerType, TaxIdKind
from erp.modules.customer.infrastructure import CustomerModel, CustomerRepository
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
class CustomerFixture:
    database: Database
    company_id: UUID
    other_company_id: UUID
    actor_id: UUID

    def customer(
        self,
        *,
        legal_name: str = "Cliente fixture",
        other_company: bool = False,
        identity_value: str = "52998224725",
    ) -> Customer:
        return Customer.create(
            company_id=self.other_company_id if other_company else self.company_id,
            customer_type=CustomerType.INDIVIDUAL,
            identity_type=TaxIdKind.CPF,
            identity_value=identity_value,
            legal_name=legal_name,
        )


@asynccontextmanager
async def customer_fixture() -> AsyncIterator[CustomerFixture]:
    database = Database(get_settings())
    actor_id = uuid4()
    group = EconomicGroup.create(code=f"T{uuid4().hex[:20]}", name="M14 test fixture")
    companies = tuple(
        Company.create(
            group_id=group.id,
            code=f"T{uuid4().hex[:20]}",
            legal_name="M14 test company",
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
        yield CustomerFixture(database, companies[0].id, companies[1].id, actor_id)
    finally:
        try:
            async with database.session() as session, session.begin():
                await session.execute(
                    delete(CustomerModel).where(CustomerModel.company_id.in_(company_ids))
                )
                await session.execute(delete(CompanyModel).where(CompanyModel.id.in_(company_ids)))
                await session.execute(
                    delete(EconomicGroupModel).where(EconomicGroupModel.id == group.id)
                )
        finally:
            await database.dispose()


def test_customer_round_trip_and_actor_metadata() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data:
            item = data.customer()
            async with data.database.session() as session, session.begin():
                repository = CustomerRepository(session, company_id=data.company_id)
                await repository.add(item, actor_id=data.actor_id)
                assert await repository.get(item.id) == item
            async with data.database.session() as session:
                model = await session.get(CustomerModel, item.id)
                assert model is not None
                assert model.created_by == data.actor_id
                assert model.updated_by == data.actor_id
                assert model.identity_value == "52998224725"
                assert model.version == 1

    asyncio.run(scenario())


def test_get_and_list_are_company_scoped_even_with_known_foreign_id() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            own = data.customer(legal_name="A Cliente")
            foreign = data.customer(
                legal_name="B Cliente", other_company=True, identity_value="15350946056"
            )
            own_repo = CustomerRepository(session, company_id=data.company_id)
            foreign_repo = CustomerRepository(session, company_id=data.other_company_id)
            await own_repo.add(own, actor_id=data.actor_id)
            await foreign_repo.add(foreign, actor_id=data.actor_id)
            assert await own_repo.list() == (own,)
            assert await foreign_repo.list() == (foreign,)
            assert await own_repo.get(foreign.id) is None
            assert await own_repo.get(uuid4()) is None
            assert await CustomerRepository(session, company_id=uuid4()).list() == ()

    asyncio.run(scenario())


def test_list_pagination_type_and_status_filter() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            repository = CustomerRepository(session, company_id=data.company_id)
            for name, cpf in (
                ("C Cliente", "52998224725"),
                ("A Cliente", "15350946056"),
                ("B Cliente", "11144477735"),
            ):
                await repository.add(
                    data.customer(legal_name=name, identity_value=cpf), actor_id=data.actor_id
                )
            await session.execute(
                update(CustomerModel)
                .where(CustomerModel.legal_name == "B Cliente")
                .values(status=CustomerStatus.BLOCKED, version=2)
            )
            assert [item.legal_name for item in await repository.list()] == [
                "A Cliente",
                "B Cliente",
                "C Cliente",
            ]
            assert [item.legal_name for item in await repository.list(limit=1, offset=1)] == [
                "B Cliente"
            ]
            assert [
                item.legal_name for item in await repository.list(status=CustomerStatus.ACTIVE)
            ] == ["A Cliente", "C Cliente"]
            assert [
                item.legal_name
                for item in await repository.list(customer_type=CustomerType.INDIVIDUAL)
            ] == ["A Cliente", "B Cliente", "C Cliente"]

    asyncio.run(scenario())


def test_company_mismatch_rejects_add_before_writing() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            foreign = data.customer(other_company=True)
            repository = CustomerRepository(session, company_id=data.company_id)
            with pytest.raises(ApplicationError, match="outside") as captured:
                await repository.add(foreign, actor_id=data.actor_id)
            assert captured.value.code == "SCOPE_FORBIDDEN"
            assert await session.get(CustomerModel, foreign.id) is None

    asyncio.run(scenario())


def test_add_does_not_commit_the_callers_transaction() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data:
            item = data.customer()
            async with data.database.session() as session:
                await CustomerRepository(session, company_id=data.company_id).add(
                    item, actor_id=data.actor_id
                )
                await session.rollback()
            async with data.database.session() as session:
                assert (
                    await CustomerRepository(session, company_id=data.company_id).get(item.id)
                    is None
                )

    asyncio.run(scenario())


def test_duplicate_identity_is_detected_per_company() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            first = data.customer()
            await CustomerRepository(session, company_id=data.company_id).add(
                first, actor_id=data.actor_id
            )
            async with session.begin_nested() as savepoint:
                with pytest.raises(ApplicationError) as captured:
                    await CustomerRepository(session, company_id=data.company_id).add(
                        data.customer(legal_name="Duplicado"), actor_id=data.actor_id
                    )
                assert captured.value.code == "CUSTOMER_DUPLICATE_EXACT_MATCH"
                assert captured.value.status_code == 409
                await savepoint.rollback()
            await CustomerRepository(session, company_id=data.other_company_id).add(
                data.customer(other_company=True), actor_id=data.actor_id
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (101, 0), (True, 0), (1, -1), (1, True)])
def test_rejects_invalid_pagination(limit: int, offset: int) -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session:
            with pytest.raises(ValueError, match=r"limit|offset"):
                await CustomerRepository(session, company_id=data.company_id).list(
                    limit=limit, offset=offset
                )

    asyncio.run(scenario())


def test_rejects_absent_context_invalid_initial_state_and_filters() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session:
            with pytest.raises(ValueError, match="company"):
                CustomerRepository(session, company_id=None)  # type: ignore[arg-type]
            repository = CustomerRepository(session, company_id=data.company_id)
            with pytest.raises(ValueError, match="actor"):
                await repository.add(data.customer(), actor_id=None)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="version one"):
                await repository.add(replace(data.customer(), version=2), actor_id=data.actor_id)
            with pytest.raises(ValueError, match="active"):
                await repository.add(
                    replace(data.customer(), status=CustomerStatus.BLOCKED),
                    actor_id=data.actor_id,
                )
            with pytest.raises(ValueError, match="status"):
                await repository.list(status="INVALID")  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="type"):
                await repository.list(customer_type="INVALID")  # type: ignore[arg-type]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("customer_type", "BAD"),
        ("identity_type", "BAD"),
        ("identity_value", "abc"),
        ("legal_name", " "),
        ("trade_name", " "),
        ("status", "BAD"),
        ("version", 0),
        ("company_id", uuid4()),
        ("created_by", None),
    ],
)
def test_database_rejects_invalid_values(field: str, value: object) -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            item = data.customer()
            await CustomerRepository(session, company_id=data.company_id).add(
                item, actor_id=data.actor_id
            )
            async with session.begin_nested() as savepoint:
                with pytest.raises(IntegrityError):
                    await session.execute(
                        update(CustomerModel)
                        .where(CustomerModel.id == item.id)
                        .values({field: value})
                    )
                await savepoint.rollback()

    asyncio.run(scenario())


def test_missing_foundation_company_fails_without_customer_insert() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session:
            item = replace(data.customer(), company_id=uuid4())
            with pytest.raises(IntegrityError):
                await CustomerRepository(session, company_id=item.company_id).add(
                    item, actor_id=data.actor_id
                )
            await session.rollback()
            assert (
                await session.scalar(select(CustomerModel.id).where(CustomerModel.id == item.id))
                is None
            )

    asyncio.run(scenario())
