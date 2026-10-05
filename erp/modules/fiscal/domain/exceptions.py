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


__all__ = [
    "FiscalDomainError",
    "ImmutableDocumentError",
    "InvalidAccessKeyError",
    "InvalidFiscalContractError",
    "InvalidStateTransitionError",
    "InvalidTaxSnapshotError",
    "TaxMismatchError",
]
