"""Internal M14 persistence adapters, wired only at the composition boundary."""

from erp.modules.customer.infrastructure.contact_address_model import (
    CustomerAddressModel,
    CustomerContactModel,
)
from erp.modules.customer.infrastructure.customer_model import CustomerModel
from erp.modules.customer.infrastructure.customer_repository import CustomerRepository
from erp.modules.customer.infrastructure.group_model import (
    CustomerGroupMemberModel,
    CustomerGroupModel,
)

__all__ = [
    "CustomerAddressModel",
    "CustomerContactModel",
    "CustomerGroupMemberModel",
    "CustomerGroupModel",
    "CustomerModel",
    "CustomerRepository",
]
