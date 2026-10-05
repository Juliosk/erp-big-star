"""Framework-free M11 domain failures."""


class FiscalDomainError(ValueError):
    """Base error for invalid fiscal domain state."""


class InvalidAccessKeyError(FiscalDomainError):
    """Raised when an NF-e/NFC-e access key is structurally invalid."""


class InvalidTaxSnapshotError(FiscalDomainError):
    """Raised when an immutable tax snapshot violates fiscal invariants."""


class InvalidFiscalContractError(FiscalDomainError):
    """Raised when a public fiscal integration contract is inconsistent."""


__all__ = [
    "FiscalDomainError",
    "InvalidAccessKeyError",
    "InvalidFiscalContractError",
    "InvalidTaxSnapshotError",
]
