"""Transaction-owning PostgreSQL adapter for M11 fiscal use cases."""

from datetime import datetime
from uuid import UUID

from erp.modules.fiscal.application.documents import (
    FiscalDocumentPage,
    FiscalIssueResult,
    IssueFiscalDocument,
)
from erp.modules.fiscal.domain import (
    FiscalDocument,
    FiscalDocumentConflictError,
    FiscalDocumentModel,
    FiscalDocumentStatus,
    FiscalVersionConflictError,
    InvalidStateTransitionError,
)
from erp.modules.fiscal.infrastructure.fiscal_document_repository import (
    FiscalDocumentRepository,
)
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyService


class PostgresFiscalDocumentStore:
    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def create(self, document: FiscalDocument, *, actor_id: UUID) -> FiscalDocument:
        try:
            async with self._database.session() as session, session.begin():
                await FiscalDocumentRepository(
                    session, company_id=document.company_id
                ).add(document, actor_id=actor_id)
                return document
        except FiscalDocumentConflictError as error:
            raise ApplicationError(
                code="FISCAL_DOCUMENT_CONFLICT", message=str(error), status_code=409
            ) from error

    async def issue(
        self, command: IssueFiscalDocument, *, actor_id: UUID
    ) -> FiscalIssueResult:
        try:
            async with self._database.session() as session, session.begin():
                decision = await self._idempotency.begin(
                    session,
                    scope=f"fiscal:{command.company_id}:{actor_id}",
                    operation="fiscal.document.issue",
                    key=command.idempotency_key,
                    payload={
                        "company_id": str(command.company_id),
                        "document_id": str(command.document_id),
                        "expected_version": command.expected_version,
                    },
                )
                repository = FiscalDocumentRepository(session, company_id=command.company_id)
                if decision.replayed:
                    document = await repository.get(command.document_id)
                    if document is None:
                        raise RuntimeError("Stored fiscal issue replay has no document.")
                    return FiscalIssueResult(document, True)
                before = await repository.get(command.document_id)
                if before is None:
                    raise ApplicationError(
                        code="RESOURCE_NOT_FOUND",
                        message="Fiscal document not found.",
                        status_code=404,
                    )
                if before.version != command.expected_version:
                    raise ApplicationError(
                        code="VERSION_CONFLICT",
                        message="The resource was changed by another transaction.",
                        status_code=409,
                    )
                try:
                    changed = before.start_issuing()
                except InvalidStateTransitionError as error:
                    raise ApplicationError(
                        code="INVALID_STATE_TRANSITION", message=str(error), status_code=409
                    ) from error
                saved = await repository.save(
                    changed, actor_id=actor_id, expected_version=command.expected_version
                )
                await self._idempotency.complete(
                    session,
                    decision,
                    response_status=202,
                    response_body={"document_id": str(saved.id), "version": saved.version},
                )
                return FiscalIssueResult(saved)
        except FiscalVersionConflictError as error:
            raise ApplicationError(
                code="VERSION_CONFLICT",
                message="The resource was changed by another transaction.",
                status_code=409,
            ) from error

    async def get(self, company_id: UUID, document_id: UUID) -> FiscalDocument | None:
        async with self._database.session() as session:
            return await FiscalDocumentRepository(session, company_id=company_id).get(document_id)

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
    ) -> FiscalDocumentPage:
        async with self._database.session() as session:
            repository = FiscalDocumentRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list(
                status=status,
                access_key=access_key,
                model=model,
                created_from=created_from,
                created_to=created_to,
                limit=page_size,
                offset=offset,
            )
            more = await repository.list(
                status=status,
                access_key=access_key,
                model=model,
                created_from=created_from,
                created_to=created_to,
                limit=1,
                offset=offset + page_size,
            )
            return FiscalDocumentPage(items, page, page_size, bool(more))


__all__ = ["PostgresFiscalDocumentStore"]
