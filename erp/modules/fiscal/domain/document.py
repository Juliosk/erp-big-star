"""Pure fiscal document enumerations."""

from enum import StrEnum


class FiscalDocumentModel(StrEnum):
    NFE = "55"
    NFCE = "65"


class FiscalDocumentStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class FiscalAuthorizationStatus(StrEnum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"


__all__ = [
    "FiscalAuthorizationStatus",
    "FiscalDocumentModel",
    "FiscalDocumentStatus",
]
