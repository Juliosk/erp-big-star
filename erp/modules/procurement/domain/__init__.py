"""Pure M6 procurement domain surface."""

from erp.modules.procurement.domain.exceptions import (
    DuplicateSupplierSiteError,
    InvalidSupplierDataError,
    InvalidSupplierIdentityError,
    InvalidSupplierTransitionError,
    ProcurementDomainError,
)
from erp.modules.procurement.domain.identity import (
    SupplierIdentityKind,
    SupplierTaxIdentity,
)
from erp.modules.procurement.domain.site import SupplierAddress, SupplierSite
from erp.modules.procurement.domain.supplier import Supplier, SupplierKind, SupplierStatus

__all__ = [
    "DuplicateSupplierSiteError",
    "InvalidSupplierDataError",
    "InvalidSupplierIdentityError",
    "InvalidSupplierTransitionError",
    "ProcurementDomainError",
    "Supplier",
    "SupplierAddress",
    "SupplierIdentityKind",
    "SupplierKind",
    "SupplierSite",
    "SupplierStatus",
    "SupplierTaxIdentity",
]
