"""Framework-free M11 domain failures."""


class FiscalDomainError(ValueError):
    """Base error for invalid fiscal domain state."""


class InvalidAccessKeyError(FiscalDomainError):
    """Raised when an NF-e/NFC-e access key is structurally invalid."""


class InvalidTaxSnapshotError(FiscalDomainError):
    """Raised when an immutable tax snapshot violates fiscal invariants."""


class InvalidFiscalContractError(FiscalDomainError):
    """Raised when a public fiscal integration contract is inconsistent."""


class InvalidStateTransitionError(FiscalDomainError):
    """Raised when a fiscal document lifecycle transition is forbidden."""


class TaxMismatchError(FiscalDomainError):
    """Raised when item and header fiscal totals exceed legal tolerance."""


class ImmutableDocumentError(FiscalDomainError):
    """Raised when an immutable fiscal document is changed."""


class FiscalDocumentConflictError(FiscalDomainError):
    """Raised when a fiscal identity conflicts inside its tenant scope."""


class FiscalVersionConflictError(FiscalDomainError):
    """Raised when an optimistic fiscal write targets a stale version."""


class FiscalScopeError(FiscalDomainError):
    """Raised when a fiscal aggregate crosses its explicit tenant scope."""


class InvalidInboundFiscalDocumentError(FiscalDomainError):
    """Raised when a supplier NF-e XML violates inbound fiscal invariants."""


class InvalidManifestationError(FiscalDomainError):
    """Raised when an MDE event or transition is invalid."""


__all__ = [
    "FiscalDocumentConflictError",
    "FiscalDomainError",
    "FiscalScopeError",
    "FiscalVersionConflictError",
    "ImmutableDocumentError",
    "InvalidAccessKeyError",
    "InvalidFiscalContractError",
    "InvalidInboundFiscalDocumentError",
    "InvalidManifestationError",
    "InvalidStateTransitionError",
    "InvalidTaxSnapshotError",
    "TaxMismatchError",
]
