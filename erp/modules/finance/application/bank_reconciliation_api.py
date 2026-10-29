"""Authorized application boundary for bank-reconciliation HTTP use cases."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.finance.application.bank_reconciliation import (
    BankCandidateOption,
    BankConciliationResult,
    BankStatementIngestionResult,
)
from erp.modules.finance.application.permissions import (
    FINANCE_RECONCILIATION_EXECUTE,
    FINANCE_RECONCILIATION_IMPORT,
    FINANCE_RECONCILIATION_READ,
    FinanceAuthorization,
)
from erp.modules.finance.domain import (
    BankMovement,
    BankMovementStatus,
    BankStatement,
    BankStatementSource,
)
from erp.platform.errors import ApplicationError


class BankMatchMode(StrEnum):
    SIMULATE = "SIMULATE"
    APPLY = "APPLY"


class BankResolutionMode(StrEnum):
    ACCEPT_MATCH = "ACCEPT_MATCH"
    FORCE_MATCH = "FORCE_MATCH"
    DIRECT_ENTRY = "DIRECT_ENTRY"


@dataclass(frozen=True, slots=True)
class UploadBankStatement:
    company_id: UUID
    bank_account_id: UUID
    source: BankStatementSource
    content: bytes
    original_file_name: str | None
    bank_code: str | None
    account_reference: str | None


@dataclass(frozen=True, slots=True)
class MatchBankStatement:
    company_id: UUID
    statement_id: UUID
    expected_version: int
    mode: BankMatchMode
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ResolveBankMovement:
    company_id: UUID
    statement_id: UUID
    movement_id: UUID
    expected_version: int
    mode: BankResolutionMode
    occurred_at: datetime
    candidate_id: UUID | None = None
    justification: str | None = None


@dataclass(frozen=True, slots=True)
class BankStatementPage:
    items: tuple[BankStatement, ...]
    page: int
    page_size: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class BankMovementEntry:
    statement_id: UUID
    movement: BankMovement


@dataclass(frozen=True, slots=True)
class BankMovementPage:
    items: tuple[BankMovementEntry, ...]
    page: int
    page_size: int
    has_more: bool


class BankReconciliationOperations(Protocol):
    async def upload(
        self,
        command: UploadBankStatement,
        *,
        actor_id: UUID,
    ) -> BankStatementIngestionResult: ...

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        bank_account_id: UUID | None,
        period_from: date | None,
        period_to: date | None,
    ) -> BankStatementPage: ...

    async def get(self, company_id: UUID, statement_id: UUID) -> BankStatement | None: ...

    async def list_movements(
        self,
        company_id: UUID,
        *,
        status: BankMovementStatus | None,
        statement_id: UUID | None,
        page: int,
        page_size: int,
    ) -> BankMovementPage: ...

    async def candidate_options(
        self,
        company_id: UUID,
        statement_id: UUID,
        movement_id: UUID,
    ) -> tuple[BankCandidateOption, ...]: ...

    async def match(
        self,
        command: MatchBankStatement,
        *,
        actor_id: UUID,
    ) -> BankConciliationResult: ...

    async def resolve(
        self,
        command: ResolveBankMovement,
        *,
        actor_id: UUID,
    ) -> BankConciliationResult: ...


class BankReconciliationApplicationService:
    def __init__(
        self,
        operations: BankReconciliationOperations,
        authorization: FinanceAuthorization,
    ) -> None:
        self._operations = operations
        self._authorization = authorization

    async def upload(
        self,
        context: SecurityContext,
        command: UploadBankStatement,
    ) -> BankStatementIngestionResult:
        await self._authorization.require(
            context,
            command.company_id,
            FINANCE_RECONCILIATION_IMPORT,
            write=True,
        )
        return await self._operations.upload(
            command,
            actor_id=context.principal.user_id,
        )

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        bank_account_id: UUID | None,
        period_from: date | None,
        period_to: date | None,
    ) -> BankStatementPage:
        await self._authorization.require(
            context,
            company_id,
            FINANCE_RECONCILIATION_READ,
        )
        return await self._operations.list(
            company_id,
            page=page,
            page_size=page_size,
            bank_account_id=bank_account_id,
            period_from=period_from,
            period_to=period_to,
        )

    async def get(
        self,
        context: SecurityContext,
        company_id: UUID,
        statement_id: UUID,
    ) -> BankStatement:
        await self._authorization.require(
            context,
            company_id,
            FINANCE_RECONCILIATION_READ,
        )
        value = await self._operations.get(company_id, statement_id)
        if value is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Bank statement not found.",
                status_code=404,
            )
        return value

    async def movements(
        self,
        context: SecurityContext,
        company_id: UUID,
        statement_id: UUID,
        *,
        status: BankMovementStatus | None,
    ) -> tuple[BankStatement, tuple[BankMovement, ...]]:
        statement = await self.get(context, company_id, statement_id)
        movements = (
            statement.movements
            if status is None
            else tuple(value for value in statement.movements if value.status is status)
        )
        return statement, movements

    async def list_movements(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        status: BankMovementStatus | None,
        statement_id: UUID | None,
        page: int,
        page_size: int,
    ) -> BankMovementPage:
        await self._authorization.require(
            context,
            company_id,
            FINANCE_RECONCILIATION_READ,
        )
        return await self._operations.list_movements(
            company_id,
            status=status,
            statement_id=statement_id,
            page=page,
            page_size=page_size,
        )

    async def candidate_options(
        self,
        context: SecurityContext,
        company_id: UUID,
        statement_id: UUID,
        movement_id: UUID,
    ) -> tuple[BankCandidateOption, ...]:
        await self._authorization.require(
            context,
            company_id,
            FINANCE_RECONCILIATION_READ,
        )
        return await self._operations.candidate_options(
            company_id,
            statement_id,
            movement_id,
        )

    async def match(
        self,
        context: SecurityContext,
        command: MatchBankStatement,
    ) -> BankConciliationResult:
        await self._authorization.require(
            context,
            command.company_id,
            FINANCE_RECONCILIATION_EXECUTE,
            write=True,
        )
        return await self._operations.match(
            command,
            actor_id=context.principal.user_id,
        )

    async def resolve(
        self,
        context: SecurityContext,
        command: ResolveBankMovement,
    ) -> BankConciliationResult:
        await self._authorization.require(
            context,
            command.company_id,
            FINANCE_RECONCILIATION_EXECUTE,
            write=True,
        )
        return await self._operations.resolve(
            command,
            actor_id=context.principal.user_id,
        )


__all__ = [
    "BankMatchMode",
    "BankMovementEntry",
    "BankMovementPage",
    "BankReconciliationApplicationService",
    "BankReconciliationOperations",
    "BankResolutionMode",
    "BankStatementPage",
    "MatchBankStatement",
    "ResolveBankMovement",
    "UploadBankStatement",
]
