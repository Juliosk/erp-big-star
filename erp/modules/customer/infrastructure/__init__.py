"""Internal M14 persistence adapters, wired only at the composition boundary."""

from erp.modules.customer.infrastructure.customer_model import CustomerModel
from erp.modules.customer.infrastructure.customer_repository import CustomerRepository

__all__ = ["CustomerModel", "CustomerRepository"]
