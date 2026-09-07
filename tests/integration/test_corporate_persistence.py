"""PostgreSQL integration proofs for the M1 corporate hierarchy."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from erp.modules.admin.domain import Branch, Company, EconomicGroup
from erp.modules.admin.infrastructure import (
    BranchRepository,
    CompanyModel,
    CompanyRepository,
    EconomicGroupRepository,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.config import get_settings
from erp.platform.database import Database


def _unique_cnpj() -> str:
    base = f"12{uuid4().int % 10_000_000_000:010d}"

    def digit(value: str, weights: tuple[int, ...]) -> str:
        remainder = (
            sum(int(number) * weight for number, weight in zip(value, weights, strict=True)) % 11
        )
        result = 11 - remainder
        return str(0 if result >= 10 else result)

    first = digit(base, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    second = digit(base + first, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return base + first + second


def _code(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}".upper()


@pytest.mark.integration
def test_corporate_hierarchy_round_trips_and_versions_all_aggregates() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        groups = EconomicGroupRepository()
        companies = CompanyRepository()
        branches = BranchRepository()
        group = EconomicGroup.create(code=_code("GRP"), name="Big Star Group")
        company = Company.create(
            group_id=group.id,
            code=_code("COMP"),
            legal_name="Big Star Industria e Comercio Ltda",
            trade_name="Big Star",
            tax_id=_unique_cnpj(),
            timezone="America/Sao_Paulo",
        )
        branch = Branch.create(
            company_id=company.id,
            code=_code("BR"),
            name="Matriz",
            tax_id=_unique_cnpj(),
            timezone="America/Sao_Paulo",
        )
        actor_id = uuid4()
        try:
            async with database.session() as session, session.begin():
                await groups.add(session, group, actor_id=actor_id)
                await companies.add(session, company, actor_id=actor_id)
                await branches.add(session, branch, actor_id=actor_id)

            async with database.session() as session, session.begin():
                saved_group = await groups.save(session, group.deactivate(), actor_id=actor_id)
                saved_company = await companies.save(
                    session,
                    company.deactivate(),
                    actor_id=actor_id,
                )
                saved_branch = await branches.save(
                    session,
                    branch.deactivate(),
                    actor_id=actor_id,
                )

            async with database.session() as session:
                stored_group = await groups.get(session, group.id)
                stored_company = await companies.get(session, company.id)
                stored_branch = await branches.get(session, branch.id)

            assert saved_group.version == saved_company.version == saved_branch.version == 2
            assert stored_group == saved_group
            assert stored_company == saved_company
            assert stored_branch == saved_branch
        finally:
            await database.dispose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_company_requires_an_existing_economic_group() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        try:
            async with database.session() as session:
                transaction = await session.begin()
                session.add(
                    CompanyModel(
                        id=uuid4(),
                        group_id=uuid4(),
                        code=_code("ORPHAN"),
                        legal_name="Orphan Company",
                        trade_name=None,
                        tax_id=_unique_cnpj(),
                        timezone="America/Sao_Paulo",
                        status="ACTIVE",
                        version=1,
                    )
                )
                with pytest.raises(IntegrityError):
                    await session.flush()
                await transaction.rollback()
        finally:
            await database.dispose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_company_tax_id_is_globally_unique() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        groups = EconomicGroupRepository()
        companies = CompanyRepository()
        group = EconomicGroup.create(code=_code("TAX"), name="Tax Group")
        tax_id = _unique_cnpj()
        first = Company.create(
            group_id=group.id,
            code=_code("FIRST"),
            legal_name="First Company",
            trade_name=None,
            tax_id=tax_id,
            timezone="America/Sao_Paulo",
        )
        duplicate = Company.create(
            group_id=group.id,
            code=_code("SECOND"),
            legal_name="Second Company",
            trade_name=None,
            tax_id=tax_id,
            timezone="America/Sao_Paulo",
        )
        try:
            async with database.session() as session:
                transaction = await session.begin()
                await groups.add(session, group, actor_id=None)
                await companies.add(session, first, actor_id=None)
                with pytest.raises(IntegrityError):
                    await companies.add(session, duplicate, actor_id=None)
                await transaction.rollback()
        finally:
            await database.dispose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_stale_company_version_cannot_overwrite_a_newer_state() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        groups = EconomicGroupRepository()
        companies = CompanyRepository()
        group = EconomicGroup.create(code=_code("LOCK"), name="Concurrency Group")
        company = Company.create(
            group_id=group.id,
            code=_code("LOCKED"),
            legal_name="Versioned Company",
            trade_name=None,
            tax_id=_unique_cnpj(),
            timezone="America/Sao_Paulo",
        )
        try:
            async with database.session() as session, session.begin():
                await groups.add(session, group, actor_id=None)
                await companies.add(session, company, actor_id=None)

            stale_candidate = company.deactivate()
            async with database.session() as session, session.begin():
                current = await companies.save(session, company.deactivate(), actor_id=None)

            async def stale_update() -> None:
                async with database.session() as session, session.begin():
                    await companies.save(session, stale_candidate, actor_id=None)

            with pytest.raises(OptimisticLockError) as captured:
                await stale_update()
            async with database.session() as session:
                stored = await companies.get(session, company.id)

            assert current.version == 2
            assert captured.value.code == "VERSION_CONFLICT"
            assert stored == current
        finally:
            await database.dispose()

    asyncio.run(scenario())
