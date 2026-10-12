"""Atomic Audit and Outbox effects for M11 fiscal lifecycle transitions."""

from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.fiscal.application.events import (
    FiscalDocumentAuthorized,
    FiscalDomainEvent,
    integration_effects,
)
from erp.modules.fiscal.application.issuance import FiscalWorkerMetadata
from erp.modules.fiscal.domain import FiscalDocument, NFeAccessKey
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


async def record_fiscal_effect(
    session: AsyncSession,
    *,
    before: FiscalDocument,
    after: FiscalDocument,
    event: FiscalDomainEvent,
    actor_id: UUID,
    metadata: FiscalWorkerMetadata,
) -> tuple[UUID, UUID]:
    event_type = type(event).__name__
    before_snapshot = fiscal_snapshot(before)
    after_snapshot = fiscal_snapshot(after)
    audit_id = await AuditService().record(
        session,
        AuditEvent(
            actor_user_id=actor_id,
            company_id=after.company_id,
            branch_id=None,
            module="fiscal",
            entity_type="fiscal_document",
            entity_id=after.id,
            operation=event_type,
            request_id=metadata.request_id,
            correlation_id=metadata.correlation_id,
            source_ip=metadata.source_ip,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        ),
    )
    payload = _event_payload(event)
    payload["integration_effects"] = [str(effect) for effect in integration_effects(event)]
    payload.update(
        {
            "document_number": f"{after.model.value}-{after.series}-{after.number}",
            "supplier_tax_id": after.issuer.tax_id,
            "currency": "BRL",
            "requested_by": str(actor_id),
        }
    )
    if isinstance(event, FiscalDocumentAuthorized):
        payload["installments"] = [
            {
                "due_date": event.authorized_at.date().isoformat(),
                "amount": str(event.total_amount),
            }
        ]
    envelope = MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=event_type,
        event_version=1,
        producer_module="fiscal",
        producer_domain="fiscal",
        aggregate_type="fiscal_document",
        aggregate_id=after.id,
        aggregate_version=after.version,
        company_id=after.company_id,
        branch_id=None,
        correlation_id=metadata.correlation_id,
        request_id=metadata.request_id,
        causation_id=None,
        payload=payload,
    )
    await OutboxService().enqueue(session, envelope)
    return envelope.message_id, audit_id


def fiscal_snapshot(document: FiscalDocument) -> dict[str, object]:
    return {
        "id": str(document.id),
        "company_id": str(document.company_id),
        "model": str(document.model),
        "series": document.series,
        "number": document.number,
        "status": str(document.status),
        "access_key": None if document.access_key is None else str(document.access_key),
        "authorization_protocol": document.authorization_protocol,
        "rejection_code": document.rejection_code,
        "rejection_reason": document.rejection_reason,
        "total_amount": str(document.totals.total_amount),
        "version": document.version,
    }


def _event_payload(event: FiscalDomainEvent) -> dict[str, object]:
    return {field.name: _json_value(getattr(event, field.name)) for field in fields(event)}


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (UUID, NFeAccessKey, Decimal, StrEnum)):
        return str(value)
    return value


__all__ = ["fiscal_snapshot", "record_fiscal_effect"]
