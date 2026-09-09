"""Public domain model for M14 Customer Core."""

from erp.modules.customer.domain.address import CustomerAddress, CustomerAddressRole
from erp.modules.customer.domain.contact import (
    CustomerContact,
    CustomerContactKind,
    CustomerContactRole,
)
from erp.modules.customer.domain.customer import Customer, CustomerStatus, CustomerType
from erp.modules.customer.domain.duplicate import (
    CustomerDuplicateCandidate,
    CustomerMergeRequest,
    DuplicateReason,
    MergeRequestStatus,
    detect_duplicate_candidates,
)
from erp.modules.customer.domain.group import CustomerGroup, CustomerGroupMember
from erp.modules.customer.domain.tax_id import CustomerTaxId, TaxIdKind

__all__ = [
    "Customer",
    "CustomerAddress",
    "CustomerAddressRole",
    "CustomerContact",
    "CustomerContactKind",
    "CustomerContactRole",
    "CustomerDuplicateCandidate",
    "CustomerGroup",
    "CustomerGroupMember",
    "CustomerMergeRequest",
    "CustomerStatus",
    "CustomerTaxId",
    "CustomerType",
    "DuplicateReason",
    "MergeRequestStatus",
    "TaxIdKind",
    "detect_duplicate_candidates",
]
