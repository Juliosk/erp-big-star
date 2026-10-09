"""DANFE/DANFCE PDF and official XML package generation."""

from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from erp.modules.fiscal.application import DanfeGenerator, FiscalXmlPackager
from erp.modules.fiscal.domain import (
    FiscalDocument,
    FiscalDocumentModel,
    FiscalDocumentStatus,
)
from erp.platform.errors import ApplicationError
from tests.unit.modules.fiscal.domain.test_fiscal_document import access_key, draft


def authorized(
    model: FiscalDocumentModel = FiscalDocumentModel.NFE,
) -> FiscalDocument:
    key = access_key(model.value)
    return (
        draft(model=model)
        .start_issuing()
        .authorize(
            access_key=key,
            protocol="135260000000001",
            authorized_at=datetime(2026, 10, 8, 12, tzinfo=UTC),
            authorized_xml=(
                f'<NFe xmlns="http://www.portalfiscal.inf.br/nfe"><infNFe Id="NFe{key}"/></NFe>'
            ),
        )
    )


@pytest.mark.parametrize(
    ("model", "title", "has_qr"),
    [
        (FiscalDocumentModel.NFE, "DANFE", False),
        (FiscalDocumentModel.NFCE, "DANFCE", True),
    ],
)
def test_generator_creates_valid_pdf_with_machine_verifiable_codes(
    model: FiscalDocumentModel, title: str, has_qr: bool
) -> None:
    document = authorized(model)
    content = DanfeGenerator().generate(document)
    reader = PdfReader(BytesIO(content))

    assert content.startswith(b"%PDF-")
    assert len(reader.pages) == 1
    assert reader.metadata is not None
    assert title in (reader.metadata.title or "")
    assert f"code128={document.access_key}" in (reader.metadata.keywords or "")
    assert ("qrcode=" in (reader.metadata.keywords or "")) is has_qr
    text = reader.pages[0].extract_text()
    assert document.issuer.legal_name in text
    assert "TOTAL: R$ 19.00" in text
    assert (
        " ".join(str(document.access_key)[index : index + 4] for index in range(0, 44, 4)) in text
    )


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (draft(), "SEM VALOR FISCAL - RASCUNHO"),
        (
            authorized().cancel(
                protocol="2", cancelled_at=datetime.now(UTC), cancellation_xml="<procEventoNFe/>"
            ),
            "CANCELADA",
        ),
    ],
)
def test_generator_adds_status_watermark(document: FiscalDocument, expected: str) -> None:
    text = PdfReader(BytesIO(DanfeGenerator().generate(document))).pages[0].extract_text()
    assert expected in text


def test_generator_adds_contingency_watermark() -> None:
    text = (
        PdfReader(BytesIO(DanfeGenerator().generate(authorized(), contingency=True)))
        .pages[0]
        .extract_text()
    )
    assert "EM CONTINGENCIA" in text


def test_xml_packager_builds_nfe_process_and_cancellation_event() -> None:
    document = authorized()
    packager = FiscalXmlPackager()
    authorized_xml = packager.authorized(document)
    root = ET.fromstring(authorized_xml)
    assert root.tag.endswith("nfeProc")
    assert root.find(".//{*}NFe") is not None
    assert root.findtext(".//{*}nProt") == "135260000000001"
    assert root.findtext(".//{*}cStat") == "100"

    cancelled = document.cancel(
        protocol="135260000000002",
        cancelled_at=datetime(2026, 10, 8, 13, tzinfo=UTC),
        cancellation_xml=(
            '<evento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">'
            "<infEvento><tpEvento>110111</tpEvento></infEvento></evento>"
        ),
    )
    event_xml = packager.cancellation(cancelled)
    event = ET.fromstring(event_xml)
    assert event.tag.endswith("procEventoNFe")
    assert event.findtext(".//{*}tpEvento") == "110111"
    assert event.findtext(".//{*}nProt") == "135260000000002"
    assert event.findtext(".//{*}cStat") == "135"


def test_packager_reuses_already_processed_xml_and_rejects_non_final_documents() -> None:
    document = authorized()
    processed = replace(
        document,
        authorized_xml=(
            '<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">'
            "<NFe/><protNFe/></nfeProc>"
        ),
    )
    assert ET.fromstring(FiscalXmlPackager().authorized(processed)).tag.endswith("nfeProc")

    with pytest.raises(ApplicationError) as error:
        FiscalXmlPackager().authorized(draft())
    assert error.value.code == "FISCAL_DOCUMENT_NOT_EXPORTABLE"
    with pytest.raises(ApplicationError):
        FiscalXmlPackager().cancellation(document)


def test_cancelled_document_requires_cancellation_payload_for_distribution() -> None:
    document = authorized().cancel(protocol="2", cancelled_at=datetime.now(UTC))
    assert document.status is FiscalDocumentStatus.CANCELLED
    with pytest.raises(ApplicationError):
        FiscalXmlPackager().cancellation(document)
