"""Public domain model for M14 Customer Core."""

from erp.modules.customer.domain.address import CustomerAddress, CustomerAddressRole
from erp.modules.customer.domain.contact import (
    CustomerContact,
    CustomerContactKind,
    CustomerContactRole,
)
from erp.modules.customer.domain.customer import Customer, CustomerStatus, CustomerType
from erp.modules.customer.domain.tax_id import CustomerTaxId, TaxIdKind

__all__ = [
    "Customer",
    "CustomerAddress",
    "CustomerAddressRole",
    "CustomerContact",
    "CustomerContactKind",
    "CustomerContactRole",
    "CustomerStatus",
    "CustomerTaxId",
    "CustomerType",
    "TaxIdKind",
]
