"""PostgreSQL transaction boundary for fiscal issuance results and events."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from erp.modules.fiscal.application.events import (
    FiscalDocumentAuthorized,
    FiscalDocumentCancelled,
    FiscalDocumentDenied,
    FiscalDocumentRejected,
)
from erp.modules.fiscal.application.issuance import (
    CancelFiscalDocument,
    TransmitFiscalDocument,
)
from erp.modules.fiscal.application.sefaz import SefazProtocolResult, SefazSubmissionResult
from erp.modules.fiscal.domain import (
    FiscalAuthorizationStatus,
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalVersionConflictError,
    NFeAccessKey,
    SefazResponseSnapshot,
)
from erp.modules.fiscal.infrastructure.fiscal_document_repository import (
    FiscalDocumentRepository,
)
from erp.modules.fiscal.infrastructure.fiscal_effects import record_fiscal_effect
from erp.platform.database import Database
from erp.platform.errors import ApplicationError


class PostgresFiscalIssuanceStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get(self, company_id: UUID, document_id: UUID) -> FiscalDocument | None:
        async with self._database.session() as session:
            return await FiscalDocumentRepository(session, company_id=company_id).get(document_id)

    async def complete_issuance(
        self,
        command: TransmitFiscalDocument,
        result: SefazSubmissionResult | SefazProtocolResult,
    ) -> FiscalDocument:
        try:
            async with self._database.session() as session, session.begin():
                repository = FiscalDocumentRepository(session, company_id=command.company_id)
                before = await repository.get(command.document_id)
                if before is None:
                    raise _not_found()
                _require_current(before, command.expected_version, FiscalDocumentStatus.ISSUING)
                response = _response_snapshot(result)
                after, event = _issuance_transition(
                    before, result, response, expected_access_key=command.access_key
                )
                saved = await repository.save(
                    after, actor_id=command.actor_id, expected_version=command.expected_version
                )
                await record_fiscal_effect(
                    session,
                    before=before,
                    after=saved,
                    event=event,
                    actor_id=command.actor_id,
                    metadata=command.metadata,
                )
                return saved
        except FiscalVersionConflictError as error:
            raise _version_conflict() from error

    async def complete_cancellation(
        self,
        command: CancelFiscalDocument,
        *,
        protocol: str,
        cancelled_at: datetime,
        event_xml: str,
        status_code: str,
        message: str,
    ) -> FiscalDocument:
        try:
            async with self._database.session() as session, session.begin():
                repository = FiscalDocumentRepository(session, company_id=command.company_id)
                before = await repository.get(command.document_id)
                if before is None:
                    raise _not_found()
                _require_current(before, command.expected_version, FiscalDocumentStatus.AUTHORIZED)
                assert before.access_key is not None
                response = SefazResponseSnapshot(
                    uuid4(), status_code, message, cancelled_at, protocol
                )
                after = before.cancel(
                    protocol=protocol,
                    cancelled_at=cancelled_at,
                    cancellation_xml=event_xml,
                    sefaz_response=response,
                )
                event = FiscalDocumentCancelled(
                    after.company_id,
                    after.id,
                    before.access_key,
                    protocol,
                    cancelled_at,
                    after.version,
                )
                saved = await repository.save(
                    after, actor_id=command.actor_id, expected_version=command.expected_version
                )
                await record_fiscal_effect(
                    session,
                    before=before,
                    after=saved,
                    event=event,
                    actor_id=command.actor_id,
                    metadata=command.metadata,
                )
                return saved
        except FiscalVersionConflictError as error:
            raise _version_conflict() from error


def _issuance_transition(
    before: FiscalDocument,
    result: SefazSubmissionResult | SefazProtocolResult,
    response: SefazResponseSnapshot,
    *,
    expected_access_key: NFeAccessKey,
) -> tuple[
    FiscalDocument,
    FiscalDocumentAuthorized | FiscalDocumentRejected | FiscalDocumentDenied,
]:
    if result.status_code == "100":
        if (
            result.status is not FiscalAuthorizationStatus.AUTHORIZED
            or result.access_key is None
            or result.protocol is None
            or result.authorized_at is None
            or result.authorized_xml is None
            or result.access_key != expected_access_key
        ):
            raise ApplicationError(
                code="INVALID_SEFAZ_RESPONSE",
                message="Authorized SEFAZ response is incomplete.",
                status_code=502,
            )
        after = before.authorize(
            access_key=result.access_key,
            protocol=result.protocol,
            authorized_at=result.authorized_at,
            authorized_xml=result.authorized_xml,
            sefaz_response=response,
        )
        return after, FiscalDocumentAuthorized(
            after.company_id,
            after.id,
            after.model,
            result.access_key,
            result.protocol,
            result.authorized_at,
            after.totals.total_amount,
            after.version,
        )
    if result.status_code in {"301", "302"}:
        after = before.deny(
            code=result.status_code, reason=result.message, sefaz_response=response
        )
        return after, FiscalDocumentDenied(
            after.company_id, after.id, result.status_code, result.message, after.version
        )
    if result.status_code in {"204", "539"}:
        after = before.reject(
            code=result.status_code, reason=result.message, sefaz_response=response
        )
        return after, FiscalDocumentRejected(
            after.company_id, after.id, result.status_code, result.message, after.version
        )
    raise ApplicationError(
        code="UNSUPPORTED_SEFAZ_RESPONSE",
        message=f"Unsupported SEFAZ cStat {result.status_code}.",
        status_code=502,
    )


def _response_snapshot(
    result: SefazSubmissionResult | SefazProtocolResult,
) -> SefazResponseSnapshot:
    return SefazResponseSnapshot(
        uuid4(),
        result.status_code,
        result.message,
        result.authorized_at or datetime.now(UTC),
        result.protocol,
    )


def _require_current(
    document: FiscalDocument, expected_version: int, expected_status: FiscalDocumentStatus
) -> None:
    if document.version != expected_version:
        raise _version_conflict()
    if document.status is not expected_status:
        raise ApplicationError(
            code="INVALID_STATE_TRANSITION",
            message=f"Fiscal document must be {expected_status}.",
            status_code=409,
        )


def _not_found() -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND", message="Fiscal document not found.", status_code=404
    )


def _version_conflict() -> ApplicationError:
    return ApplicationError(
        code="VERSION_CONFLICT",
        message="The resource was changed by another transaction.",
        status_code=409,
    )


__all__ = ["PostgresFiscalIssuanceStore"]
