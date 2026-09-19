"""Integration coverage for the tenant-bound M15 quote repository."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, update

from erp.modules.customer.infrastructure import CustomerModel
from erp.modules.product.infrastructure import ProductRepository
from erp.modules.sales.domain import SalesQuote
from erp.modules.sales.infrastructure import (
    QuoteRevisionItemModel,
    QuoteRevisionModel,
    SalesQuoteModel,
    SalesQuoteRepository,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError
from tests.integration.test_product_persistence import Fixture, fixture

pytestmark = pytest.mark.integration


def _identity() -> str:
    return f"{uuid4().int % 100_000_000_000_000:014d}"


async def _seed_customer(data: Fixture, *, company_id: UUID) -> UUID:
    customer_id = uuid4()
    async with data.database.session() as session, session.begin():
        session.add(
            CustomerModel(
                id=customer_id,
                company_id=company_id,
                customer_type="COMPANY",
                identity_type="CNPJ",
                identity_value=_identity(),
                legal_name="Sales quote customer",
                trade_name=None,
                status="ACTIVE",
                version=1,
                created_by=data.actor_id,
                updated_by=data.actor_id,
            )
        )
    return customer_id


async def _cleanup_sales(data: Fixture) -> None:
    company_ids = (data.company_id, data.other_company_id)
    async with data.database.session() as session, session.begin():
        await session.execute(
            delete(QuoteRevisionItemModel).where(
                QuoteRevisionItemModel.company_id.in_(company_ids)
            )
        )
        await session.execute(
            delete(QuoteRevisionModel).where(QuoteRevisionModel.company_id.in_(company_ids))
        )
        await session.execute(
            delete(SalesQuoteModel).where(SalesQuoteModel.company_id.in_(company_ids))
        )
        await session.execute(
            delete(CustomerModel).where(CustomerModel.company_id.in_(company_ids))
        )


@asynccontextmanager
async def sales_fixture() -> AsyncIterator[Fixture]:
    async with fixture() as data:
        try:
            yield data
        finally:
            await _cleanup_sales(data)


def _quote(data: Fixture, customer_id: UUID, *, other_company: bool = False) -> SalesQuote:
    return SalesQuote.create(
        company_id=data.other_company_id if other_company else data.company_id,
        number=f"Q-{uuid4().hex[:12].upper()}",
        customer_id=customer_id,
        seller_id=data.actor_id,
    )


def test_quote_repository_is_company_scoped_and_allows_numbers_per_company() -> None:
    async def scenario() -> None:
        async with sales_fixture() as data:
            own_customer = await _seed_customer(data, company_id=data.company_id)
            foreign_customer = await _seed_customer(data, company_id=data.other_company_id)
            own = _quote(data, own_customer)
            foreign = SalesQuote.create(
                company_id=data.other_company_id,
                number=own.number,
                customer_id=foreign_customer,
                seller_id=data.actor_id,
            )
            async with data.database.session() as session, session.begin():
                own_repo = SalesQuoteRepository(session, company_id=data.company_id)
                foreign_repo = SalesQuoteRepository(session, company_id=data.other_company_id)
                await own_repo.add(own, actor_id=data.actor_id)
                await foreign_repo.add(foreign, actor_id=data.actor_id)

                assert await own_repo.get(own.id) == own
                assert await own_repo.get(foreign.id) is None
                assert await own_repo.list() == (own,)
                assert await foreign_repo.list() == (foreign,)

    asyncio.run(scenario())


def test_quote_repository_persists_immutable_revision_and_optimistic_version() -> None:
    async def scenario() -> None:
        async with sales_fixture() as data:
            customer_id = await _seed_customer(data, company_id=data.company_id)
            product = data.product(code="QUOTE-LINE")
            original = _quote(data, customer_id)
            changed, revision = original.revise(
                lines=((product.id, "2.500000", "19.90", "1.00"),)
            )
            async with data.database.session() as session, session.begin():
                await ProductRepository(session, company_id=data.company_id).add(
                    product, actor_id=data.actor_id
                )
                repository = SalesQuoteRepository(session, company_id=data.company_id)
                await repository.add(original, actor_id=data.actor_id)
                stored = await repository.add_revision(
                    changed,
                    revision,
                    actor_id=data.actor_id,
                    expected_version=original.version,
                )

                assert stored == changed
                assert await repository.get_revision(original.id, 1) == revision
                assert await repository.list(customer_id=customer_id) == (changed,)

    asyncio.run(scenario())


def test_quote_repository_rejects_foreign_scope_duplicate_and_stale_write() -> None:
    async def scenario() -> None:
        async with sales_fixture() as data:
            customer_id = await _seed_customer(data, company_id=data.company_id)
            quote = _quote(data, customer_id)
            async with data.database.session() as session, session.begin():
                repository = SalesQuoteRepository(session, company_id=data.company_id)
                with pytest.raises(ApplicationError) as scope_error:
                    await repository.add(
                        _quote(data, uuid4(), other_company=True), actor_id=data.actor_id
                    )
                assert scope_error.value.code == "SCOPE_FORBIDDEN"
                await repository.add(quote, actor_id=data.actor_id)

                async with session.begin_nested():
                    duplicate = SalesQuote.create(
                        company_id=data.company_id,
                        number=quote.number,
                        customer_id=customer_id,
                        seller_id=data.actor_id,
                    )
                    with pytest.raises(ApplicationError) as duplicate_error:
                        await repository.add(duplicate, actor_id=data.actor_id)
                    assert duplicate_error.value.code == "SALES_QUOTE_CONFLICT"

                product = data.product(code="STALE-LINE")
                await ProductRepository(session, company_id=data.company_id).add(
                    product, actor_id=data.actor_id
                )
                changed, revision = quote.revise(
                    lines=((product.id, "1.000000", "10.00", "0.00"),)
                )
                await session.execute(
                    update(SalesQuoteModel)
                    .where(SalesQuoteModel.id == quote.id)
                    .values(version=2)
                    .execution_options(synchronize_session=False)
                )
                with pytest.raises(OptimisticLockError):
                    await repository.add_revision(
                        changed,
                        revision,
                        actor_id=data.actor_id,
                        expected_version=quote.version,
                    )

    asyncio.run(scenario())
