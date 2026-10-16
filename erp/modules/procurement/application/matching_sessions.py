"""Authorized commands and queries for M6 three-way matching sessions."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.procurement.application.matching import MatchingExecutionResult
from erp.modules.procurement.application.permissions import (
    PROCUREMENT_MATCHING_EXECUTE,
    PROCUREMENT_MATCHING_READ,
    ProcurementAuthorization,
)
from erp.modules.procurement.application.purchasing import ProcurementCommandMetadata
from erp.modules.procurement.domain import ThreeWayMatchSession, ThreeWayMatchSessionStatus
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class MatchingLineReferenceInput:
    match_key: str
    purchase_order_item_id: UUID
    goods_receipt_item_id: UUID
    fiscal_document_item_id: UUID


@dataclass(frozen=True, slots=True)
class CreateMatchingSession:
    company_id: UUID
    purchase_order_id: UUID
    goods_receipt_ids: tuple[UUID, ...]
    inbound_fiscal_document_ids: tuple[UUID, ...]
    provisional_entry_id: UUID
    payable_id: UUID | None
    unit_price_variance_percentage: Decimal
    quantity_variance_percentage: Decimal
    rounding_absolute_limit: Decimal
    tolerance_policy_version: int
    lines: tuple[MatchingLineReferenceInput, ...]
    idempotency_key: str

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "purchase_order_id": str(self.purchase_order_id),
            "goods_receipt_ids": [str(value) for value in self.goods_receipt_ids],
            "inbound_fiscal_document_ids": [
                str(value) for value in self.inbound_fiscal_document_ids
            ],
            "provisional_entry_id": str(self.provisional_entry_id),
            "payable_id": str(self.payable_id) if self.payable_id is not None else None,
            "unit_price_variance_percentage": str(self.unit_price_variance_percentage),
            "quantity_variance_percentage": str(self.quantity_variance_percentage),
            "rounding_absolute_limit": str(self.rounding_absolute_limit),
            "tolerance_policy_version": self.tolerance_policy_version,
            "lines": [
                {
                    "match_key": line.match_key,
                    "purchase_order_item_id": str(line.purchase_order_item_id),
                    "goods_receipt_item_id": str(line.goods_receipt_item_id),
                    "fiscal_document_item_id": str(line.fiscal_document_item_id),
                }
                for line in self.lines
            ],
        }


@dataclass(frozen=True, slots=True)
class ExecuteMatchingSession:
    company_id: UUID
    matching_session_id: UUID
    expected_version: int
    idempotency_key: str
    metadata: ProcurementCommandMetadata
    occurred_at: datetime | None = None

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "matching_session_id": str(self.matching_session_id),
            "expected_version": self.expected_version,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at is not None else None,
        }


@dataclass(frozen=True, slots=True)
class MatchingAuditEntry:
    id: UUID
    from_status: ThreeWayMatchSessionStatus | None
    to_status: ThreeWayMatchSessionStatus
    aggregate_version: int
    actor_id: UUID
    occurred_at: datetime
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class MatchingSessionDetail:
    session: ThreeWayMatchSession
    audit_history: tuple[MatchingAuditEntry, ...]


@dataclass(frozen=True, slots=True)
class MatchingSessionPage:
    items: tuple[ThreeWayMatchSession, ...]
    page: int
    page_size: int
    has_more: bool


class MatchingCommandStore(Protocol):
    async def create(
        self, command: CreateMatchingSession, *, actor_id: UUID
    ) -> ThreeWayMatchSession: ...

    async def execute(
        self, command: ExecuteMatchingSession, *, actor_id: UUID
    ) -> MatchingExecutionResult: ...


class MatchingQueryStore(Protocol):
    async def get_detail(
        self, company_id: UUID, matching_session_id: UUID
    ) -> MatchingSessionDetail | None: ...

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: ThreeWayMatchSessionStatus | None,
        purchase_order_id: UUID | None,
    ) -> MatchingSessionPage: ...


class MatchingCommandService:
    def __init__(
        self,
        store: MatchingCommandStore,
        authorization: ProcurementAuthorization,
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def create(
        self, context: SecurityContext, command: CreateMatchingSession
    ) -> ThreeWayMatchSession:
        await self._authorization.require(
            context,
            command.company_id,
            PROCUREMENT_MATCHING_EXECUTE,
            write=True,
        )
        return await self._store.create(command, actor_id=context.principal.user_id)

    async def execute(
        self, context: SecurityContext, command: ExecuteMatchingSession
    ) -> MatchingExecutionResult:
        await self._authorization.require(
            context,
            command.company_id,
            PROCUREMENT_MATCHING_EXECUTE,
            write=True,
        )
        return await self._store.execute(command, actor_id=context.principal.user_id)


class MatchingQueryService:
    def __init__(
        self,
        store: MatchingQueryStore,
        authorization: ProcurementAuthorization,
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def get(
        self,
        context: SecurityContext,
        company_id: UUID,
        matching_session_id: UUID,
    ) -> MatchingSessionDetail:
        await self._authorization.require(context, company_id, PROCUREMENT_MATCHING_READ)
        value = await self._store.get_detail(company_id, matching_session_id)
        if value is None:
            raise _not_found()
        return value

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: ThreeWayMatchSessionStatus | None = None,
        purchase_order_id: UUID | None = None,
    ) -> MatchingSessionPage:
        await self._authorization.require(context, company_id, PROCUREMENT_MATCHING_READ)
        _page(page, page_size)
        return await self._store.list(
            company_id,
            page=page,
            page_size=page_size,
            status=status,
            purchase_order_id=purchase_order_id,
        )

    async def exception_queue(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        purchase_order_id: UUID | None = None,
    ) -> MatchingSessionPage:
        return await self.list(
            context,
            company_id,
            page=page,
            page_size=page_size,
            status=ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED,
            purchase_order_id=purchase_order_id,
        )


def _page(page: int, page_size: int) -> None:
    if (
        type(page) is not int
        or not 1 <= page <= 100_000
        or type(page_size) is not int
        or not 1 <= page_size <= 100
    ):
        raise ApplicationError(
            code="VALIDATION_ERROR",
            message="Invalid matching session pagination.",
            status_code=422,
        )


def _not_found() -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND",
        message="Three-way matching session not found.",
        status_code=404,
    )


__all__ = [
    "CreateMatchingSession",
    "ExecuteMatchingSession",
    "MatchingAuditEntry",
    "MatchingCommandService",
    "MatchingCommandStore",
    "MatchingLineReferenceInput",
    "MatchingQueryService",
    "MatchingQueryStore",
    "MatchingSessionDetail",
    "MatchingSessionPage",
]
