"""Session-owning PostgreSQL adapter for M15 quote queries and creation."""

from uuid import UUID

from erp.modules.sales.application.quotes import (
    SalesQuoteDetail,
    SalesQuotePage,
    SalesQuoteStore,
)
from erp.modules.sales.domain import QuoteRevision, SalesQuote, SalesQuoteStatus
from erp.modules.sales.infrastructure.repository import SalesQuoteRepository
from erp.platform.database import Database


class PostgresSalesQuotes(SalesQuoteStore):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(self, quote: SalesQuote, actor_id: UUID) -> SalesQuote:
        async with self._database.session() as session, session.begin():
            await SalesQuoteRepository(session, company_id=quote.company_id).add(
                quote, actor_id=actor_id
            )
        return quote

    async def list(
        self,
        company_id: UUID,
        *,
        status: SalesQuoteStatus | None,
        customer_id: UUID | None,
        page: int,
        page_size: int,
    ) -> SalesQuotePage:
        offset = (page - 1) * page_size
        async with self._database.session() as session:
            repository = SalesQuoteRepository(session, company_id=company_id)
            items = await repository.list(
                status=status, customer_id=customer_id, limit=page_size, offset=offset
            )
            more = await repository.list(
                status=status,
                customer_id=customer_id,
                limit=1,
                offset=offset + page_size,
            )
        return SalesQuotePage(items, page, page_size, bool(more))

    async def get(self, company_id: UUID, quote_id: UUID) -> SalesQuoteDetail | None:
        async with self._database.session() as session:
            repository = SalesQuoteRepository(session, company_id=company_id)
            quote = await repository.get(quote_id)
            if quote is None:
                return None
            revisions: list[QuoteRevision] = []
            for number in range(1, quote.current_revision_number + 1):
                revision = await repository.get_revision(quote.id, number)
                if revision is not None:
                    revisions.append(revision)
        return SalesQuoteDetail(quote, tuple(revisions))


__all__ = ["PostgresSalesQuotes"]
