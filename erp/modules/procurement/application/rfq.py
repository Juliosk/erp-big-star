"""Framework-neutral RFQ lifecycle and adjudication service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from erp.modules.procurement.application.purchasing import ProcurementCommandMetadata
from erp.modules.procurement.domain import (
    RequestForQuotation,
    RequestForQuotationVersionConflictError,
    SupplierQuote,
)
from erp.platform.errors import ApplicationError

REQUEST_FOR_QUOTATION_OPENED = "RequestForQuotationOpened"
SUPPLIER_QUOTE_RECORDED = "SupplierQuoteRecorded"
REQUEST_FOR_QUOTATION_CLOSED = "RequestForQuotationClosed"
REQUEST_FOR_QUOTATION_AWARDED = "RequestForQuotationAwarded"
REQUEST_FOR_QUOTATION_CANCELLED = "RequestForQuotationCancelled"


@dataclass(frozen=True, slots=True)
class ChangeRequestForQuotation:
    company_id: UUID
    rfq_id: UUID
    expected_version: int
    metadata: ProcurementCommandMetadata = field(default_factory=ProcurementCommandMetadata.new)


@dataclass(frozen=True, slots=True)
class RequestForQuotationMutationResult:
    rfq: RequestForQuotation
    event_id: UUID
    audit_id: UUID


class RequestForQuotationStore(Protocol):
    async def get_for_update(self, rfq_id: UUID) -> RequestForQuotation | None: ...

    async def save(
        self,
        rfq: RequestForQuotation,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> RequestForQuotation: ...


class RequestForQuotationEffectsPort(Protocol):
    async def record(
        self,
        *,
        before: RequestForQuotation,
        after: RequestForQuotation,
        event_type: str,
        actor_id: UUID,
        metadata: ProcurementCommandMetadata,
    ) -> tuple[UUID, UUID]: ...


class RequestForQuotationApplicationService:
    """Coordinate the complete RFQ lifecycle with observable atomic effects."""

    def __init__(
        self,
        repository: RequestForQuotationStore,
        effects: RequestForQuotationEffectsPort,
    ) -> None:
        self._repository = repository
        self._effects = effects

    async def open(
        self,
        command: ChangeRequestForQuotation,
        *,
        actor_id: UUID,
        occurred_at: datetime,
    ) -> RequestForQuotationMutationResult:
        return await self._change(
            command,
            actor_id=actor_id,
            event_type=REQUEST_FOR_QUOTATION_OPENED,
            transition=lambda rfq: rfq.open(occurred_at=occurred_at),
        )

    async def record_quote(
        self,
        command: ChangeRequestForQuotation,
        *,
        actor_id: UUID,
        quote: SupplierQuote,
    ) -> RequestForQuotationMutationResult:
        return await self._change(
            command,
            actor_id=actor_id,
            event_type=SUPPLIER_QUOTE_RECORDED,
            transition=lambda rfq: rfq.record_quote(quote),
        )

    async def close(
        self,
        command: ChangeRequestForQuotation,
        *,
        actor_id: UUID,
        occurred_at: datetime,
    ) -> RequestForQuotationMutationResult:
        return await self._change(
            command,
            actor_id=actor_id,
            event_type=REQUEST_FOR_QUOTATION_CLOSED,
            transition=lambda rfq: rfq.close(occurred_at=occurred_at),
        )

    async def award(
        self,
        command: ChangeRequestForQuotation,
        *,
        actor_id: UUID,
        quote_id: UUID,
        occurred_at: datetime,
    ) -> RequestForQuotationMutationResult:
        return await self._change(
            command,
            actor_id=actor_id,
            event_type=REQUEST_FOR_QUOTATION_AWARDED,
            transition=lambda rfq: rfq.award_quote(
                quote_id=quote_id,
                actor_id=actor_id,
                occurred_at=occurred_at,
            ),
        )

    async def cancel(
        self,
        command: ChangeRequestForQuotation,
        *,
        actor_id: UUID,
        reason: str,
    ) -> RequestForQuotationMutationResult:
        return await self._change(
            command,
            actor_id=actor_id,
            event_type=REQUEST_FOR_QUOTATION_CANCELLED,
            transition=lambda rfq: rfq.cancel(reason=reason),
        )

    async def _change(
        self,
        command: ChangeRequestForQuotation,
        *,
        actor_id: UUID,
        event_type: str,
        transition: Callable[[RequestForQuotation], RequestForQuotation],
    ) -> RequestForQuotationMutationResult:
        current = await self._load(command)
        changed = transition(current)
        saved = await self._repository.save(
            changed,
            actor_id=actor_id,
            expected_version=current.version,
        )
        event_id, audit_id = await self._effects.record(
            before=current,
            after=saved,
            event_type=event_type,
            actor_id=actor_id,
            metadata=command.metadata,
        )
        return RequestForQuotationMutationResult(saved, event_id, audit_id)

    async def _load(self, command: ChangeRequestForQuotation) -> RequestForQuotation:
        _validate_change(command)
        current = await self._repository.get_for_update(command.rfq_id)
        if current is None or current.company_id != command.company_id:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Request for quotation not found.",
                status_code=404,
            )
        if current.version != command.expected_version:
            raise RequestForQuotationVersionConflictError(
                f"RFQ expected version {command.expected_version} is stale."
            )
        return current


def _validate_change(command: ChangeRequestForQuotation) -> None:
    if not isinstance(command, ChangeRequestForQuotation):
        raise TypeError("command must be a ChangeRequestForQuotation.")
    for value, field_name in (
        (command.company_id, "company_id"),
        (command.rfq_id, "rfq_id"),
    ):
        if not isinstance(value, UUID) or value.int == 0:
            raise ValueError(f"{field_name} must be a non-zero UUID.")
    if (
        not isinstance(command.expected_version, int)
        or isinstance(command.expected_version, bool)
        or command.expected_version < 1
    ):
        raise ValueError("expected_version must be a positive integer.")


__all__ = [
    "REQUEST_FOR_QUOTATION_AWARDED",
    "REQUEST_FOR_QUOTATION_CANCELLED",
    "REQUEST_FOR_QUOTATION_CLOSED",
    "REQUEST_FOR_QUOTATION_OPENED",
    "SUPPLIER_QUOTE_RECORDED",
    "ChangeRequestForQuotation",
    "RequestForQuotationApplicationService",
    "RequestForQuotationEffectsPort",
    "RequestForQuotationMutationResult",
    "RequestForQuotationStore",
]
