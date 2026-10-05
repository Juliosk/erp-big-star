"""M11 explicit document and authorization states."""

from erp.modules.fiscal.domain import (
    FiscalAuthorizationStatus,
    FiscalDocumentModel,
    FiscalDocumentStatus,
)


def test_supported_document_models_are_nfe_and_nfce() -> None:
    assert set(FiscalDocumentModel) == {FiscalDocumentModel.NFE, FiscalDocumentModel.NFCE}
    assert FiscalDocumentModel.NFE.value == "55"
    assert FiscalDocumentModel.NFCE.value == "65"


def test_authorization_and_document_states_are_explicit() -> None:
    assert set(FiscalAuthorizationStatus) == {
        FiscalAuthorizationStatus.PENDING,
        FiscalAuthorizationStatus.AUTHORIZED,
        FiscalAuthorizationStatus.REJECTED,
        FiscalAuthorizationStatus.DENIED,
        FiscalAuthorizationStatus.UNKNOWN,
    }
    assert FiscalDocumentStatus.AUTHORIZED.value == "AUTHORIZED"
    assert FiscalDocumentStatus.REJECTED.value == "REJECTED"
    assert FiscalDocumentStatus.CANCELLED.value == "CANCELLED"
