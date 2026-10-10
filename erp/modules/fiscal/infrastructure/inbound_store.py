"""PostgreSQL unit of work for inbound NF-e and MDE operations."""

from datetime import datetime
from uuid import UUID

from erp.modules.fiscal.application.inbound import InboundNFeParser, ManifestInboundDocument
from erp.modules.fiscal.application.inbound_documents import InboundResult
from erp.modules.fiscal.application.sefaz import SefazEndpoint, SefazEnvironment, SefazGatewayPort
from erp.modules.fiscal.domain import (
    FiscalDocumentConflictError,
    FiscalVersionConflictError,
    InboundFiscalDocument,
    InvalidInboundFiscalDocumentError,
    RecipientManifestation,
    RecipientManifestationStatus,
    RecipientManifestationType,
)
from erp.modules.fiscal.infrastructure.inbound_repository import InboundFiscalDocumentRepository
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.idempotency import IdempotencyService


class PostgresInboundFiscalOperations:
    def __init__(self, database: Database, gateway: SefazGatewayPort, *, ttl_seconds: int) -> None:
        self._database = database
        self._gateway = gateway
        self._parser = InboundNFeParser()
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def upload(
        self, company_id: UUID, actor_id: UUID, payload: bytes, key: str
    ) -> InboundResult:
        try:
            document = self._parser.parse(company_id, payload)
        except InvalidInboundFiscalDocumentError as error:
            raise ApplicationError(
                code="INVALID_INBOUND_FISCAL_XML",
                message="Inbound NF-e XML is invalid.",
                status_code=422,
                details=[ErrorDetail(message=str(error))],
            ) from error
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"fiscal-inbound:{company_id}:{actor_id}",
                operation="upload",
                key=key,
                payload={"company_id": str(company_id), "xml": document.source_xml},
            )
            repository = InboundFiscalDocumentRepository(session, company_id=company_id)
            if decision.replayed:
                stored = await repository.get(UUID(str((decision.response_body or {})["id"])))
                if stored is None:
                    raise RuntimeError("Idempotent inbound response references a missing document.")
                return InboundResult(stored, True)
            try:
                await repository.add(document, actor_id=actor_id)
            except FiscalDocumentConflictError as error:
                raise ApplicationError(
                    code="FISCAL_INBOUND_CONFLICT",
                    message="Inbound NF-e access key already exists.",
                    status_code=409,
                ) from error
            await self._idempotency.complete(
                session, decision, response_status=201, response_body={"id": str(document.id)}
            )
            return InboundResult(document)

    async def manifest(
        self,
        company_id: UUID,
        actor_id: UUID,
        document_id: UUID,
        expected_version: int,
        event_type: RecipientManifestationType,
        reason: str | None,
        key: str,
    ) -> InboundResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"fiscal-inbound:{company_id}:{actor_id}",
                operation=f"manifest:{document_id}",
                key=key,
                payload={
                    "document_id": str(document_id),
                    "version": expected_version,
                    "event_type": event_type.value,
                    "reason": reason,
                },
            )
            repository = InboundFiscalDocumentRepository(session, company_id=company_id)
            if decision.replayed:
                stored = await repository.get(document_id)
                if stored is None:
                    raise RuntimeError("Idempotent MDE response references a missing document.")
                return InboundResult(stored, True)
            document = await repository.get(document_id)
            if document is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Inbound fiscal document not found.",
                    status_code=404,
                )
            if document.version != expected_version:
                raise _version_conflict()
            command = ManifestInboundDocument(
                company_id=company_id,
                document_id=document_id,
                expected_version=expected_version,
                event_type=event_type,
                endpoint=SefazEndpoint(
                    document.recipient.state_code, SefazEnvironment.HOMOLOGATION
                ),
                reason=reason,
            )
            sequence = document.next_manifestation_sequence(command.event_type, command.reason)
            from erp.modules.fiscal.application.sefaz import SefazManifestationRequest

            result = await self._gateway.manifest_recipient(
                SefazManifestationRequest(
                    access_key=document.access_key,
                    event_type=event_type,
                    event_sequence=sequence,
                    endpoint=command.endpoint,
                    recipient_tax_id=document.recipient.tax_id,
                    reason=reason,
                )
            )
            if not result.accepted or result.protocol is None or result.registered_at is None:
                raise ApplicationError(
                    code="FISCAL_MANIFESTATION_REJECTED", message=result.message, status_code=409
                )
            updated = document.register_manifestation(
                RecipientManifestation(
                    event_type=event_type,
                    sequence=sequence,
                    registered_at=result.registered_at,
                    protocol=result.protocol,
                    status_code=result.status_code,
                    reason=reason,
                    event_xml=result.event_xml,
                )
            )
            try:
                await repository.save(updated, actor_id=actor_id, expected_version=expected_version)
            except FiscalVersionConflictError as error:
                raise _version_conflict() from error
            await self._idempotency.complete(
                session, decision, response_status=200, response_body={"id": str(document_id)}
            )
            return InboundResult(updated)

    async def get(self, company_id: UUID, document_id: UUID) -> InboundFiscalDocument | None:
        async with self._database.session() as session:
            return await InboundFiscalDocumentRepository(session, company_id=company_id).get(
                document_id
            )

    async def list(
        self,
        company_id: UUID,
        *,
        access_key: str | None,
        supplier_tax_id: str | None,
        mde_status: RecipientManifestationStatus | None,
        issued_from: datetime | None,
        issued_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[InboundFiscalDocument, ...]:
        async with self._database.session() as session:
            return await InboundFiscalDocumentRepository(session, company_id=company_id).list(
                access_key=access_key,
                supplier_tax_id=supplier_tax_id,
                mde_status=mde_status,
                issued_from=issued_from,
                issued_to=issued_to,
                limit=limit,
                offset=offset,
            )


def _version_conflict() -> ApplicationError:
    return ApplicationError(
        code="VERSION_CONFLICT",
        message="The inbound fiscal document changed in another transaction.",
        status_code=409,
    )


__all__ = ["PostgresInboundFiscalOperations"]
