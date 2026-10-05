"""Public framework-free M11 domain surface."""

from erp.modules.fiscal.domain.access_key import NFeAccessKey
from erp.modules.fiscal.domain.document import (
    FiscalAuthorizationStatus,
    FiscalDocumentModel,
    FiscalDocumentStatus,
)
from erp.modules.fiscal.domain.exceptions import (
    FiscalDomainError,
    ImmutableDocumentError,
    InvalidAccessKeyError,
    InvalidFiscalContractError,
    InvalidStateTransitionError,
    InvalidTaxSnapshotError,
    TaxMismatchError,
)
from erp.modules.fiscal.domain.fiscal_document import (
    LEGAL_ROUNDING_TOLERANCE,
    FiscalDocument,
    FiscalDocumentItem,
    FiscalDocumentTotals,
    FiscalPartySnapshot,
)
from erp.modules.fiscal.domain.tax_snapshot import (
    TaxComponentSnapshot,
    TaxKind,
    TaxSnapshot,
)

__all__ = [
    "LEGAL_ROUNDING_TOLERANCE",
    "FiscalAuthorizationStatus",
    "FiscalDocument",
    "FiscalDocumentItem",
    "FiscalDocumentModel",
    "FiscalDocumentStatus",
    "FiscalDocumentTotals",
    "FiscalDomainError",
    "FiscalPartySnapshot",
    "ImmutableDocumentError",
    "InvalidAccessKeyError",
    "InvalidFiscalContractError",
    "InvalidStateTransitionError",
    "InvalidTaxSnapshotError",
    "NFeAccessKey",
    "TaxComponentSnapshot",
    "TaxKind",
    "TaxMismatchError",
    "TaxSnapshot",
]
