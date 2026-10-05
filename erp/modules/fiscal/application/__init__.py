"""Public M11 application surface."""

from erp.modules.fiscal.application.permissions import (
    FISCAL_NFE_CANCEL,
    FISCAL_NFE_CORRECT,
    FISCAL_NFE_ISSUE,
    FISCAL_NFE_READ,
    fiscal_permission_registry,
)

__all__ = [
    "FISCAL_NFE_CANCEL",
    "FISCAL_NFE_CORRECT",
    "FISCAL_NFE_ISSUE",
    "FISCAL_NFE_READ",
    "fiscal_permission_registry",
]
