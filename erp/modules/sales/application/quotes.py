"""Application use cases for creating and querying M15 quotes."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.application.permissions import (
    SALES_QUOTE_CREATE,
    SALES_QUOTE_READ,
    SalesAuthorization,
)
from erp.modules.sales.domain import QuoteRevision, SalesQuote, SalesQuoteStatus
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class SalesQuotePage:
    items: tuple[SalesQuote, ...]
    page: int
    page_size: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class SalesQuoteDetail:
    quote: SalesQuote
    revisions: tuple[QuoteRevision, ...]


@dataclass(frozen=True, slots=True)
class CreateSalesQuote:
    company_id: UUID
    number: str
    customer_id: UUID
    currency: str = "BRL"


class SalesQuoteStore(Protocol):
    async def create(self, quote: SalesQuote, actor_id: UUID) -> SalesQuote: ...

    async def list(
        self,
        company_id: UUID,
        *,
        status: SalesQuoteStatus | None,
        customer_id: UUID | None,
        page: int,
        page_size: int,
    ) -> SalesQuotePage: ...

    async def get(self, company_id: UUID, quote_id: UUID) -> SalesQuoteDetail | None: ...


class SalesQuoteService:
    def __init__(self, store: SalesQuoteStore, authorization: SalesAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create(
        self, context: SecurityContext, command: CreateSalesQuote
    ) -> SalesQuote:
        await self._authorization.require(
            context, command.company_id, SALES_QUOTE_CREATE, write=True
        )
        try:
            quote = SalesQuote.create(
                company_id=command.company_id,
                number=command.number,
                customer_id=command.customer_id,
                seller_id=context.principal.user_id,
                currency=command.currency,
            )
        except ValueError as error:
            raise _validation(str(error)) from error
        return await self._store.create(quote, context.principal.user_id)

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        status: SalesQuoteStatus | None = None,
        customer_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> SalesQuotePage:
        await self._authorization.require(context, company_id, SALES_QUOTE_READ)
        if type(page) is not int or not 1 <= page <= 100_000:
            raise _validation("Invalid page.")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise _validation("Invalid page size.")
        return await self._store.list(
            company_id,
            status=status,
            customer_id=customer_id,
            page=page,
            page_size=page_size,
        )

    async def get(
        self, context: SecurityContext, company_id: UUID, quote_id: UUID
    ) -> SalesQuoteDetail:
        await self._authorization.require(context, company_id, SALES_QUOTE_READ)
        detail = await self._store.get(company_id, quote_id)
        if detail is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Sales quote not found.", status_code=404
            )
        return detail


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid sales quote data.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = [
    "CreateSalesQuote",
    "SalesQuoteDetail",
    "SalesQuotePage",
    "SalesQuoteService",
    "SalesQuoteStore",
]
