"""Framework-neutral M11 fiscal document use cases."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.fiscal.application.permissions import (
    FISCAL_NFE_ISSUE,
    FISCAL_NFE_READ,
    FiscalAuthorization,
)
from erp.modules.fiscal.domain import (
    FiscalDocument,
    FiscalDocumentItem,
    FiscalDocumentModel,
    FiscalDocumentStatus,
    FiscalDocumentTotals,
    FiscalPartySnapshot,
)
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class CreateFiscalDocument:
    company_id: UUID
    model: FiscalDocumentModel
    series: int
    number: int
    issuer: FiscalPartySnapshot
    recipient: FiscalPartySnapshot
    items: tuple[FiscalDocumentItem, ...]
    totals: FiscalDocumentTotals | None = None


@dataclass(frozen=True, slots=True)
class IssueFiscalDocument:
    company_id: UUID
    document_id: UUID
    expected_version: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class FiscalDocumentPage:
    items: tuple[FiscalDocument, ...]
    page: int
    page_size: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class FiscalIssueResult:
    document: FiscalDocument
    idempotency_replayed: bool = False


class FiscalDocumentStore(Protocol):
    async def create(self, document: FiscalDocument, *, actor_id: UUID) -> FiscalDocument: ...

    async def issue(
        self, command: IssueFiscalDocument, *, actor_id: UUID
    ) -> FiscalIssueResult: ...

    async def get(self, company_id: UUID, document_id: UUID) -> FiscalDocument | None: ...

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: FiscalDocumentStatus | None,
        access_key: str | None,
        model: FiscalDocumentModel | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> FiscalDocumentPage: ...


class FiscalDocumentService:
    def __init__(self, store: FiscalDocumentStore, authorization: FiscalAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def create(
        self, context: SecurityContext, command: CreateFiscalDocument
    ) -> FiscalDocument:
        await self._authorization.require(
            context, command.company_id, FISCAL_NFE_ISSUE, write=True
        )
        try:
            document = FiscalDocument.create(
                company_id=command.company_id,
                model=command.model,
                series=command.series,
                number=command.number,
                issuer=command.issuer,
                recipient=command.recipient,
                items=command.items,
                totals=command.totals,
            )
        except ValueError as error:
            raise _validation_error(error) from error
        return await self._store.create(document, actor_id=context.principal.user_id)

    async def issue(
        self, context: SecurityContext, command: IssueFiscalDocument
    ) -> FiscalIssueResult:
        await self._authorization.require(
            context, command.company_id, FISCAL_NFE_ISSUE, write=True
        )
        return await self._store.issue(command, actor_id=context.principal.user_id)

    async def get(
        self, context: SecurityContext, company_id: UUID, document_id: UUID
    ) -> FiscalDocument:
        await self._authorization.require(context, company_id, FISCAL_NFE_READ)
        document = await self._store.get(company_id, document_id)
        if document is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Fiscal document not found.", status_code=404
            )
        return document

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        status: FiscalDocumentStatus | None = None,
        access_key: str | None = None,
        model: FiscalDocumentModel | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> FiscalDocumentPage:
        await self._authorization.require(context, company_id, FISCAL_NFE_READ)
        if not 1 <= page <= 100_000 or not 1 <= page_size <= 100:
            raise ApplicationError(
                code="VALIDATION_ERROR", message="Invalid pagination.", status_code=422
            )
        if created_from is not None and created_to is not None and created_from > created_to:
            raise ApplicationError(
                code="VALIDATION_ERROR",
                message="created_from must not be after created_to.",
                status_code=422,
            )
        key = None if access_key is None else access_key.strip()
        if key == "":
            raise ApplicationError(
                code="VALIDATION_ERROR", message="Access key filter cannot be empty.", status_code=422
            )
        return await self._store.list(
            company_id,
            page=page,
            page_size=page_size,
            status=status,
            access_key=key,
            model=model,
            created_from=created_from,
            created_to=created_to,
        )


def _validation_error(error: ValueError) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid fiscal document data.",
        status_code=422,
        details=[ErrorDetail(message=str(error))],
    )


__all__ = [
    "CreateFiscalDocument",
    "FiscalDocumentPage",
    "FiscalDocumentService",
    "FiscalDocumentStore",
    "FiscalIssueResult",
    "IssueFiscalDocument",
]
