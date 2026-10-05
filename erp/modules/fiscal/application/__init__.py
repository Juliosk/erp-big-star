"""Public M11 application surface."""

from erp.modules.fiscal.application.documents import (
    CreateFiscalDocument,
    FiscalDocumentPage,
    FiscalDocumentService,
    FiscalDocumentStore,
    FiscalIssueResult,
    IssueFiscalDocument,
)
from erp.modules.fiscal.application.permissions import (
    FISCAL_NFE_CANCEL,
    FISCAL_NFE_CORRECT,
    FISCAL_NFE_ISSUE,
    FISCAL_NFE_READ,
    FiscalAuthorization,
    fiscal_permission_registry,
)

__all__ = [
    "FISCAL_NFE_CANCEL",
    "FISCAL_NFE_CORRECT",
    "FISCAL_NFE_ISSUE",
    "FISCAL_NFE_READ",
    "CreateFiscalDocument",
    "FiscalAuthorization",
    "FiscalDocumentPage",
    "FiscalDocumentService",
    "FiscalDocumentStore",
    "FiscalIssueResult",
    "IssueFiscalDocument",
    "fiscal_permission_registry",
]
