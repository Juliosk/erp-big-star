"""M14 application services and technology-neutral ports."""

from erp.modules.customer.application.customer360 import Customer360Service
from erp.modules.customer.application.duplicates import CustomerDuplicateService
from erp.modules.customer.application.groups import CustomerGroupService
from erp.modules.customer.application.queries import CustomerQueries
from erp.modules.customer.application.updates import CustomerUpdateService

__all__ = [
    "Customer360Service",
    "CustomerDuplicateService",
    "CustomerGroupService",
    "CustomerQueries",
    "CustomerUpdateService",
]
