"""Transactional commands for the M15 quote lifecycle."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import PermissionCode, SecurityContext
from erp.modules.sales.application.permissions import (
    SALES_QUOTE_SEND,
    SALES_QUOTE_UPDATE,
    SalesAuthorization,
)
from erp.modules.sales.application.quotes import SalesQuoteDetail
from erp.modules.sales.domain import SalesQuoteStatus
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class CommandMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None


@dataclass(frozen=True, slots=True)
class RevisionLine:
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal = Decimal("0")
    pricing_snapshot_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ReviseSalesQuote:
    company_id: UUID
    quote_id: UUID
    expected_version: int
    lines: tuple[RevisionLine, ...]
    metadata: CommandMetadata


@dataclass(frozen=True, slots=True)
class TransitionSalesQuote:
    company_id: UUID
    quote_id: UUID
    expected_version: int
    target_status: SalesQuoteStatus
    metadata: CommandMetadata
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class SalesQuoteMutationResult:
    detail: SalesQuoteDetail
    event_id: UUID
    audit_event_id: UUID


class SalesQuoteLifecycleStore(Protocol):
    async def revise(
        self, command: ReviseSalesQuote, actor_id: UUID
    ) -> SalesQuoteMutationResult: ...

    async def transition(
        self, command: TransitionSalesQuote, actor_id: UUID
    ) -> SalesQuoteMutationResult: ...


class SalesQuoteLifecycleService:
    def __init__(self, store: SalesQuoteLifecycleStore, authorization: SalesAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def revise(
        self, context: SecurityContext, command: ReviseSalesQuote
    ) -> SalesQuoteMutationResult:
        await self._authorization.require(
            context, command.company_id, SALES_QUOTE_UPDATE, write=True
        )
        if not command.lines:
            raise _validation("A quote revision requires at least one line.")
        return await self._store.revise(command, context.principal.user_id)

    async def transition(
        self, context: SecurityContext, command: TransitionSalesQuote
    ) -> SalesQuoteMutationResult:
        permission: PermissionCode = (
            SALES_QUOTE_SEND
            if command.target_status is SalesQuoteStatus.SENT
            else SALES_QUOTE_UPDATE
        )
        await self._authorization.require(
            context, command.company_id, permission, write=True
        )
        if command.target_status not in {
            SalesQuoteStatus.SENT,
            SalesQuoteStatus.ACCEPTED,
            SalesQuoteStatus.PARTIALLY_ACCEPTED,
            SalesQuoteStatus.LOST,
        }:
            raise _validation("Unsupported quote transition.")
        return await self._store.transition(command, context.principal.user_id)


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid sales quote lifecycle command.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = [
    "CommandMetadata",
    "ReviseSalesQuote",
    "RevisionLine",
    "SalesQuoteLifecycleService",
    "SalesQuoteLifecycleStore",
    "SalesQuoteMutationResult",
    "TransitionSalesQuote",
]
