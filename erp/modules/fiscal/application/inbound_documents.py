"""Authorized use cases for inbound fiscal documents."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.fiscal.application.permissions import (
    FISCAL_INBOUND_MANAGE,
    FISCAL_INBOUND_READ,
    FiscalAuthorization,
)
from erp.modules.fiscal.domain import (
    InboundFiscalDocument,
    RecipientManifestationStatus,
    RecipientManifestationType,
)
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class InboundResult:
    document: InboundFiscalDocument
    idempotency_replayed: bool = False


@dataclass(frozen=True, slots=True)
class InboundPage:
    items: tuple[InboundFiscalDocument, ...]
    page: int
    page_size: int


class InboundFiscalOperations(Protocol):
    async def upload(
        self, company_id: UUID, actor_id: UUID, payload: bytes, key: str
    ) -> InboundResult: ...
    async def manifest(
        self,
        company_id: UUID,
        actor_id: UUID,
        document_id: UUID,
        expected_version: int,
        event_type: RecipientManifestationType,
        reason: str | None,
        key: str,
    ) -> InboundResult: ...
    async def get(self, company_id: UUID, document_id: UUID) -> InboundFiscalDocument | None: ...
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
    ) -> tuple[InboundFiscalDocument, ...]: ...


class InboundFiscalDocumentService:
    def __init__(
        self, operations: InboundFiscalOperations, authorization: FiscalAuthorization
    ) -> None:
        self._operations = operations
        self._authorization = authorization

    async def upload(
        self, context: SecurityContext, company_id: UUID, payload: bytes, key: str
    ) -> InboundResult:
        await self._authorization.require(context, company_id, FISCAL_INBOUND_MANAGE, write=True)
        return await self._operations.upload(company_id, context.principal.user_id, payload, key)

    async def manifest(
        self,
        context: SecurityContext,
        company_id: UUID,
        document_id: UUID,
        expected_version: int,
        event_type: RecipientManifestationType,
        reason: str | None,
        key: str,
    ) -> InboundResult:
        await self._authorization.require(context, company_id, FISCAL_INBOUND_MANAGE, write=True)
        return await self._operations.manifest(
            company_id,
            context.principal.user_id,
            document_id,
            expected_version,
            event_type,
            reason,
            key,
        )

    async def get(
        self, context: SecurityContext, company_id: UUID, document_id: UUID
    ) -> InboundFiscalDocument:
        await self._authorization.require(context, company_id, FISCAL_INBOUND_READ)
        value = await self._operations.get(company_id, document_id)
        if value is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Inbound fiscal document not found.",
                status_code=404,
            )
        return value

    async def list(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        access_key: str | None = None,
        supplier_tax_id: str | None = None,
        mde_status: RecipientManifestationStatus | None = None,
        issued_from: datetime | None = None,
        issued_to: datetime | None = None,
    ) -> InboundPage:
        await self._authorization.require(context, company_id, FISCAL_INBOUND_READ)
        items = await self._operations.list(
            company_id,
            access_key=access_key,
            supplier_tax_id=supplier_tax_id,
            mde_status=mde_status,
            issued_from=issued_from,
            issued_to=issued_to,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return InboundPage(items, page, page_size)


__all__ = [
    "InboundFiscalDocumentService",
    "InboundFiscalOperations",
    "InboundPage",
    "InboundResult",
]
