"""Framework-neutral orchestration for fiscal authorization and cancellation."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from erp.modules.fiscal.application.sefaz import (
    SefazBatchRequest,
    SefazCancellationRequest,
    SefazEndpoint,
    SefazGatewayPort,
    SefazProtocolResult,
    SefazSubmissionMode,
    SefazSubmissionResult,
)
from erp.modules.fiscal.domain import FiscalDocument, FiscalDocumentStatus, NFeAccessKey
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class FiscalWorkerMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None


@dataclass(frozen=True, slots=True)
class TransmitFiscalDocument:
    company_id: UUID
    document_id: UUID
    expected_version: int
    actor_id: UUID
    access_key: NFeAccessKey
    unsigned_xml: bytes
    reference_uri: str
    batch_id: str
    endpoint: SefazEndpoint
    mode: SefazSubmissionMode
    metadata: FiscalWorkerMetadata


@dataclass(frozen=True, slots=True)
class CancelFiscalDocument:
    company_id: UUID
    document_id: UUID
    expected_version: int
    actor_id: UUID
    reason: str
    endpoint: SefazEndpoint
    metadata: FiscalWorkerMetadata
    event_sequence: int = 1


class FiscalIssuanceStore(Protocol):
    async def get(self, company_id: UUID, document_id: UUID) -> FiscalDocument | None: ...

    async def complete_issuance(
        self,
        command: TransmitFiscalDocument,
        result: SefazSubmissionResult | SefazProtocolResult,
    ) -> FiscalDocument: ...

    async def complete_cancellation(
        self,
        command: CancelFiscalDocument,
        *,
        protocol: str,
        cancelled_at: datetime,
        event_xml: str,
        status_code: str,
        message: str,
    ) -> FiscalDocument: ...


class FiscalIssuanceWorker:
    def __init__(
        self,
        store: FiscalIssuanceStore,
        gateway: SefazGatewayPort,
        *,
        cancellation_window: timedelta = timedelta(hours=24),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if cancellation_window <= timedelta(0):
            raise ValueError("Cancellation window must be positive.")
        self._store = store
        self._gateway = gateway
        self._cancellation_window = cancellation_window
        self._now = now or (lambda: datetime.now(UTC))

    async def transmit(self, command: TransmitFiscalDocument) -> FiscalDocument:
        document = await self._required(command.company_id, command.document_id)
        if document.status is not FiscalDocumentStatus.ISSUING:
            raise ApplicationError(
                code="INVALID_STATE_TRANSITION",
                message="Only ISSUING fiscal documents can be transmitted.",
                status_code=409,
            )
        if document.version != command.expected_version:
            raise _version_conflict()
        if command.access_key.model != document.model.value:
            raise ApplicationError(
                code="BUSINESS_VALIDATION_ERROR",
                message="Access key model does not match the fiscal document.",
                status_code=422,
            )
        signed = await self._gateway.sign_xml(
            command.unsigned_xml, reference_uri=command.reference_uri
        )
        result: SefazSubmissionResult | SefazProtocolResult = await self._gateway.submit_batch(
            SefazBatchRequest(
                command.batch_id,
                (signed,),
                command.access_key,
                document.model,
                command.mode,
                command.endpoint,
            )
        )
        if result.status.value == "PENDING":
            if result.receipt_number is None:
                raise RuntimeError("Asynchronous SEFAZ response has no receipt number.")
            result = await self._gateway.query_protocol(
                result.endpoint, result.receipt_number
            )
        return await self._store.complete_issuance(command, result)

    async def cancel(self, command: CancelFiscalDocument) -> FiscalDocument:
        document = await self._required(command.company_id, command.document_id)
        if document.status is not FiscalDocumentStatus.AUTHORIZED:
            raise ApplicationError(
                code="INVALID_STATE_TRANSITION",
                message="Only AUTHORIZED fiscal documents can be cancelled.",
                status_code=409,
            )
        if document.version != command.expected_version:
            raise _version_conflict()
        assert document.access_key is not None
        assert document.authorization_protocol is not None
        assert document.authorized_at is not None
        if self._now() - document.authorized_at > self._cancellation_window:
            raise ApplicationError(
                code="FISCAL_CANCELLATION_WINDOW_EXPIRED",
                message="Fiscal cancellation window has expired.",
                status_code=409,
            )
        result = await self._gateway.cancel_document(
            SefazCancellationRequest(
                document.access_key,
                document.authorization_protocol,
                command.reason,
                command.event_sequence,
                command.endpoint,
            )
        )
        if (
            not result.accepted
            or result.protocol is None
            or result.cancelled_at is None
            or result.event_xml is None
        ):
            raise ApplicationError(
                code="FISCAL_CANCELLATION_REJECTED",
                message=result.message,
                status_code=409,
            )
        return await self._store.complete_cancellation(
            command,
            protocol=result.protocol,
            cancelled_at=result.cancelled_at,
            event_xml=result.event_xml,
            status_code=result.status_code,
            message=result.message,
        )

    async def _required(self, company_id: UUID, document_id: UUID) -> FiscalDocument:
        document = await self._store.get(company_id, document_id)
        if document is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Fiscal document not found.", status_code=404
            )
        return document


def _version_conflict() -> ApplicationError:
    return ApplicationError(
        code="VERSION_CONFLICT",
        message="The resource was changed by another transaction.",
        status_code=409,
    )


__all__ = [
    "CancelFiscalDocument",
    "FiscalIssuanceStore",
    "FiscalIssuanceWorker",
    "FiscalWorkerMetadata",
    "TransmitFiscalDocument",
]
