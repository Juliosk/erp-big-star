"""Pure M6 domain errors."""


class ProcurementDomainError(ValueError):
    """Base error for violated Procurement invariants."""


class InvalidSupplierIdentityError(ProcurementDomainError):
    """A fiscal identity is invalid or incompatible with the supplier kind."""


class InvalidSupplierDataError(ProcurementDomainError):
    """Supplier or site master data violates a semantic invariant."""


class InvalidSupplierTransitionError(ProcurementDomainError):
    """Supplier lifecycle transition is not allowed."""


class DuplicateSupplierSiteError(ProcurementDomainError):
    """A site identity or code is already present in the aggregate."""


class InvalidRequisitionError(ProcurementDomainError):
    """A purchase requisition invariant was violated."""


class InvalidPurchaseOrderError(ProcurementDomainError):
    """A purchase order invariant was violated."""


class InvalidProcurementTransitionError(ProcurementDomainError):
    """A requisition or purchase order lifecycle transition is not allowed."""


__all__ = [
    "DuplicateSupplierSiteError",
    "InvalidProcurementTransitionError",
    "InvalidPurchaseOrderError",
    "InvalidRequisitionError",
    "InvalidSupplierDataError",
    "InvalidSupplierIdentityError",
    "InvalidSupplierTransitionError",
    "ProcurementDomainError",
]
