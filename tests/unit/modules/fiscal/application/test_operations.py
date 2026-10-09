"""Operator fiscal command construction remains framework-free."""

import pytest

from erp.modules.fiscal.application.operations import (
    _access_key,
    _unsigned_xml,
    _validate_contingency,
)
from erp.modules.fiscal.application.sefaz import ContingencyMode
from erp.modules.fiscal.domain import FiscalDocumentModel
from erp.platform.errors import ApplicationError
from tests.unit.modules.fiscal.domain.test_fiscal_document import draft


def test_access_key_and_unsigned_xml_follow_document_identity() -> None:
    document = draft()
    key = _access_key(document, ContingencyMode.SVC_AN)
    xml = _unsigned_xml(document, key)

    assert key.model == "55"
    assert key.state_code == "35"
    assert key.value[34] == "6"
    assert f'Id="NFe{key}"'.encode() in xml
    assert b"<mod>55</mod>" in xml


def test_contingency_rejects_incompatible_document_models() -> None:
    nfe = draft()
    nfce = draft(model=FiscalDocumentModel.NFCE)

    with pytest.raises(ApplicationError) as nfe_error:
        _validate_contingency(nfe, ContingencyMode.OFFLINE_NFCE)
    assert nfe_error.value.code == "BUSINESS_VALIDATION_ERROR"

    with pytest.raises(ApplicationError) as nfce_error:
        _validate_contingency(nfce, ContingencyMode.SVC_AN)
    assert nfce_error.value.code == "BUSINESS_VALIDATION_ERROR"

    _validate_contingency(nfe, ContingencyMode.NONE)
    _validate_contingency(nfce, ContingencyMode.OFFLINE_NFCE)
