"""M12 persistence adapters."""

from erp.modules.finance.infrastructure.payable_model import (
    PayableInstallmentModel,
    PayableModel,
    ProvisionalEntryModel,
)
from erp.modules.finance.infrastructure.payable_repository import PayableRepository
from erp.modules.finance.infrastructure.payable_store import PostgresPayableStore
from erp.modules.finance.infrastructure.provisional_repository import (
    ProvisionalEntryRepository,
)
from erp.modules.finance.infrastructure.provisioning_consumer import (
    FINANCE_PAYABLE_PROVISIONING_CONSUMER,
    FISCAL_DOCUMENT_AUTHORIZED,
    FISCAL_DOCUMENT_CANCELLED,
    PURCHASE_ORDER_APPROVED,
    FiscalEventConsumer,
    PayableProvisioningConsumer,
    PayableProvisioningService,
)

__all__ = [
    "FINANCE_PAYABLE_PROVISIONING_CONSUMER",
    "FISCAL_DOCUMENT_AUTHORIZED",
    "FISCAL_DOCUMENT_CANCELLED",
    "PURCHASE_ORDER_APPROVED",
    "FiscalEventConsumer",
    "PayableInstallmentModel",
    "PayableModel",
    "PayableProvisioningConsumer",
    "PayableProvisioningService",
    "PayableRepository",
    "PostgresPayableStore",
    "ProvisionalEntryModel",
    "ProvisionalEntryRepository",
]
