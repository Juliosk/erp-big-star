"""M14 application services and technology-neutral ports."""

from erp.modules.customer.application.queries import CustomerQueries
from erp.modules.customer.application.updates import CustomerUpdateService

__all__ = ["CustomerQueries", "CustomerUpdateService"]
