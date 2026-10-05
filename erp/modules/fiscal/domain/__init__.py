"""Public framework-free M11 domain surface."""

from erp.modules.fiscal.domain.access_key import NFeAccessKey
from erp.modules.fiscal.domain.document import (
    FiscalAuthorizationStatus,
    FiscalDocumentModel,
    FiscalDocumentStatus,
)
from erp.modules.fiscal.domain.exceptions import (
    FiscalDomainError,
    InvalidAccessKeyError,
    InvalidFiscalContractError,
    InvalidTaxSnapshotError,
)
from erp.modules.fiscal.domain.tax_snapshot import (
    TaxComponentSnapshot,
    TaxKind,
    TaxSnapshot,
)

__all__ = [
    "FiscalAuthorizationStatus",
    "FiscalDocumentModel",
    "FiscalDocumentStatus",
    "FiscalDomainError",
    "InvalidAccessKeyError",
    "InvalidFiscalContractError",
    "InvalidTaxSnapshotError",
    "NFeAccessKey",
    "TaxComponentSnapshot",
    "TaxKind",
    "TaxSnapshot",
]
