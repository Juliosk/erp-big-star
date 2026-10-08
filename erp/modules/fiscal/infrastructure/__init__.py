"""Public M11 persistence surface."""

from erp.modules.fiscal.infrastructure.certificate import (
    CertificateAdapter,
    CertificateError,
    CertificateIdentity,
)
from erp.modules.fiscal.infrastructure.fiscal_document_model import (
    FiscalDocumentItemModel,
    FiscalDocumentModel,
)
from erp.modules.fiscal.infrastructure.fiscal_document_repository import (
    FiscalDocumentRepository,
)
from erp.modules.fiscal.infrastructure.fiscal_document_store import (
    PostgresFiscalDocumentStore,
)
from erp.modules.fiscal.infrastructure.sefaz_gateway import (
    CertificateSefazGateway,
    CircuitBreaker,
    CircuitState,
    ContingencyPolicy,
    ResilientSefazGateway,
    RetryPolicy,
    SefazCircuitOpenError,
    SefazGatewayError,
    SefazMockAdapter,
    SefazMockScenario,
    SefazTransientError,
)

__all__ = [
    "CertificateAdapter",
    "CertificateError",
    "CertificateIdentity",
    "CertificateSefazGateway",
    "CircuitBreaker",
    "CircuitState",
    "ContingencyPolicy",
    "FiscalDocumentItemModel",
    "FiscalDocumentModel",
    "FiscalDocumentRepository",
    "PostgresFiscalDocumentStore",
    "ResilientSefazGateway",
    "RetryPolicy",
    "SefazCircuitOpenError",
    "SefazGatewayError",
    "SefazMockAdapter",
    "SefazMockScenario",
    "SefazTransientError",
]
