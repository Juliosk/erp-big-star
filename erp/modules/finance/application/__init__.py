"""Public M12 application surface."""

from erp.modules.finance.application.permissions import (
    FINANCE_PAYABLE_ADJUST,
    FINANCE_PAYABLE_APPROVE,
    FINANCE_PAYABLE_CREATE,
    FINANCE_PAYABLE_READ,
    FinanceAuthorization,
    finance_permission_registry,
)

__all__ = [
    "FINANCE_PAYABLE_ADJUST",
    "FINANCE_PAYABLE_APPROVE",
    "FINANCE_PAYABLE_CREATE",
    "FINANCE_PAYABLE_READ",
    "FinanceAuthorization",
    "finance_permission_registry",
]
