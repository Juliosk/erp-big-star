"""Pure M11 domain-event contracts and cross-module trigger policy."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from erp.modules.fiscal.domain import FiscalDocumentModel, NFeAccessKey

FISCAL_DOCUMENT_AUTHORIZED = "FiscalDocumentAuthorized"
FISCAL_DOCUMENT_REJECTED = "FiscalDocumentRejected"
FISCAL_DOCUMENT_DENIED = "FiscalDocumentDenied"
FISCAL_DOCUMENT_CANCELLED = "FiscalDocumentCancelled"


class FiscalIntegrationEffect(StrEnum):
    INVENTORY_EFFECTUATE = "inventory.effectuate"
    RECEIVABLE_CREATE = "finance.receivable.create"
    INVENTORY_REVERSE = "inventory.reverse"
    RECEIVABLE_REVERSE = "finance.receivable.reverse"


@dataclass(frozen=True, slots=True)
class FiscalDocumentAuthorized:
    company_id: UUID
    document_id: UUID
    model: FiscalDocumentModel
    access_key: NFeAccessKey
    protocol: str
    authorized_at: datetime
    total_amount: Decimal
    version: int


@dataclass(frozen=True, slots=True)
class FiscalDocumentRejected:
    company_id: UUID
    document_id: UUID
    status_code: str
    reason: str
    version: int


@dataclass(frozen=True, slots=True)
class FiscalDocumentDenied:
    company_id: UUID
    document_id: UUID
    status_code: str
    reason: str
    version: int


@dataclass(frozen=True, slots=True)
class FiscalDocumentCancelled:
    company_id: UUID
    document_id: UUID
    access_key: NFeAccessKey
    protocol: str
    cancelled_at: datetime
    version: int


FiscalDomainEvent = (
    FiscalDocumentAuthorized
    | FiscalDocumentRejected
    | FiscalDocumentDenied
    | FiscalDocumentCancelled
)


def integration_effects(event: FiscalDomainEvent) -> tuple[FiscalIntegrationEffect, ...]:
    """Only authorization creates downstream physical and financial effects."""
    if isinstance(event, FiscalDocumentAuthorized):
        return (
            FiscalIntegrationEffect.INVENTORY_EFFECTUATE,
            FiscalIntegrationEffect.RECEIVABLE_CREATE,
        )
    if isinstance(event, FiscalDocumentCancelled):
        return (
            FiscalIntegrationEffect.INVENTORY_REVERSE,
            FiscalIntegrationEffect.RECEIVABLE_REVERSE,
        )
    return ()


__all__ = [
    "FISCAL_DOCUMENT_AUTHORIZED",
    "FISCAL_DOCUMENT_CANCELLED",
    "FISCAL_DOCUMENT_DENIED",
    "FISCAL_DOCUMENT_REJECTED",
    "FiscalDocumentAuthorized",
    "FiscalDocumentCancelled",
    "FiscalDocumentDenied",
    "FiscalDocumentRejected",
    "FiscalDomainEvent",
    "FiscalIntegrationEffect",
    "integration_effects",
]
