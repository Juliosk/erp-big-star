"""PostgreSQL proofs that corporate directory reads cannot cross tenant scopes."""

import asyncio
from uuid import uuid4

import pytest

from erp.modules.admin.domain import (
    Branch,
    Company,
    CorporateStatus,
    EconomicGroup,
    Scope,
    ScopeType,
    TenantContext,
)
from erp.modules.admin.infrastructure import (
    BranchRepository,
    CompanyRepository,
    CorporateDirectoryRepository,
    EconomicGroupRepository,
)
from erp.platform.config import get_settings
from erp.platform.database import Database


def _unique_cnpj() -> str:
    base = f"34{uuid4().int % 10_000_000_000:010d}"

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
    return f"{prefix}_{uuid4().hex[:8]}".upper()


@pytest.mark.integration
def test_directory_expands_only_the_authorized_hierarchy() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        group_repository = EconomicGroupRepository()
        company_repository = CompanyRepository()
        branch_repository = BranchRepository()
        directory = CorporateDirectoryRepository()
        group_a = EconomicGroup.create(code=_code("GA"), name="Group A")
        group_b = EconomicGroup.create(code=_code("GB"), name="Group B")
        company_a = Company.create(
            group_id=group_a.id,
            code=_code("CA"),
            legal_name="Company A",
            trade_name=None,
            tax_id=_unique_cnpj(),
            timezone="America/Sao_Paulo",
        )
        company_b = Company.create(
            group_id=group_b.id,
            code=_code("CB"),
            legal_name="Company B",
            trade_name=None,
            tax_id=_unique_cnpj(),
            timezone="America/Sao_Paulo",
        )
        branch_a = Branch.create(
            company_id=company_a.id,
            code=_code("BA"),
            name="Branch A",
            tax_id=_unique_cnpj(),
            timezone="America/Sao_Paulo",
        )
        branch_b = Branch.create(
            company_id=company_b.id,
            code=_code("BB"),
            name="Branch B",
            tax_id=_unique_cnpj(),
            timezone="America/Sao_Paulo",
        )
        try:
            async with database.session() as session, session.begin():
                for group in (group_a, group_b):
                    await group_repository.add(session, group, actor_id=None)
                for company in (company_a, company_b):
                    await company_repository.add(session, company, actor_id=None)
                for branch in (branch_a, branch_b):
                    await branch_repository.add(session, branch, actor_id=None)

            contexts = (
                (
                    TenantContext.from_scopes(
                        actor_user_id=uuid4(),
                        scopes=frozenset({Scope(ScopeType.GROUP, group_a.id)}),
                    ),
                    {group_a.id},
                    {company_a.id},
                    {branch_a.id},
                ),
                (
                    TenantContext.from_scopes(
                        actor_user_id=uuid4(),
                        scopes=frozenset({Scope(ScopeType.COMPANY, company_b.id)}),
                    ),
                    {group_b.id},
                    {company_b.id},
                    {branch_b.id},
                ),
                (
                    TenantContext.from_scopes(
                        actor_user_id=uuid4(),
                        scopes=frozenset({Scope(ScopeType.BRANCH, branch_a.id)}),
                    ),
                    {group_a.id},
                    {company_a.id},
                    {branch_a.id},
                ),
            )
            async with database.session() as session:
                for context, group_ids, company_ids, branch_ids in contexts:
                    groups = await directory.list_groups(session, context)
                    companies = await directory.list_companies(session, context)
                    branches = await directory.list_branches(session, context)
                    assert {item.id for item in groups} == group_ids
                    assert {item.id for item in companies} == company_ids
                    assert {item.id for item in branches} == branch_ids

            async with database.session() as session, session.begin():
                await branch_repository.save(session, branch_a.deactivate(), actor_id=None)
            async with database.session() as session:
                group_context = contexts[0][0]
                active = await directory.list_branches(
                    session,
                    group_context,
                    status=CorporateStatus.ACTIVE,
                )
                inactive = await directory.list_branches(
                    session,
                    group_context,
                    status=CorporateStatus.INACTIVE,
                )

            assert active == []
            assert {item.id for item in inactive} == {branch_a.id}
        finally:
            await database.dispose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_directory_is_default_deny_when_actor_has_no_scopes() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        directory = CorporateDirectoryRepository()
        context = TenantContext.from_scopes(actor_user_id=uuid4(), scopes=frozenset())
        try:
            async with database.session() as session:
                assert await directory.list_groups(session, context) == []
                assert await directory.list_companies(session, context) == []
                assert await directory.list_branches(session, context) == []
        finally:
            await database.dispose()

    asyncio.run(scenario())
