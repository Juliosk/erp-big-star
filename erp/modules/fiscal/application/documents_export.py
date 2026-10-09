"""Framework-neutral fiscal printable and distribution document services."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Protocol, cast
from uuid import UUID
from xml.etree import ElementTree as ET

from defusedxml.ElementTree import fromstring
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from erp.modules.admin.contracts import SecurityContext
from erp.modules.fiscal.application.documents import FiscalDocumentService
from erp.modules.fiscal.domain import (
    FiscalDocument,
    FiscalDocumentModel,
    FiscalDocumentStatus,
    FiscalPartySnapshot,
)
from erp.platform.errors import ApplicationError
from erp.platform.storage.objects import StoredObject

NFE_NAMESPACE = "http://www.portalfiscal.inf.br/nfe"
PDF_CONTENT_TYPE = "application/pdf"
XML_CONTENT_TYPE = "application/xml"


@dataclass(frozen=True, slots=True)
class FiscalArtifact:
    content: bytes
    content_type: str
    filename: str
    storage_key: str
    sha256: str


class FiscalArtifactStoragePort(Protocol):
    async def put(self, key: str, content: bytes, *, content_type: str) -> StoredObject: ...

    async def get(self, key: str) -> bytes: ...

    async def exists(self, key: str) -> bool: ...


class DanfeGenerator:
    """Generate compact DANFE/DANFCE representations without persistence concerns."""

    def __init__(
        self,
        *,
        nfce_query_url: str = "https://www.nfce.fazenda.gov.br/portal/consulta.aspx",
    ) -> None:
        self._nfce_query_url = nfce_query_url.rstrip("?")

    def generate(self, document: FiscalDocument, *, contingency: bool = False) -> bytes:
        output = BytesIO()
        canvas = Canvas(output, pagesize=A4, pageCompression=1)
        width, height = A4
        title = "DANFE" if document.model is FiscalDocumentModel.NFE else "DANFCE"
        canvas.setTitle(f"{title} {document.series}/{document.number}")
        canvas.setAuthor(document.issuer.legal_name)
        identifiers = [f"representation={title}"]
        if document.access_key is not None:
            identifiers.append(f"code128={document.access_key}")
            if document.model is FiscalDocumentModel.NFCE:
                identifiers.append(f"qrcode={self._nfce_query_url}?p={document.access_key}")
        canvas.setKeywords(";".join(identifiers))
        self._header(canvas, document, title, width, height)
        y = height - 80 * mm
        y = self._parties(canvas, document, y, width)
        y = self._items(canvas, document, y, width)
        self._totals(canvas, document, y, width)
        self._identifiers(canvas, document, width)
        watermark = self._watermark(document, contingency)
        if watermark:
            self._draw_watermark(canvas, watermark, width, height)
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(
            width / 2, 8 * mm, "Representacao auxiliar do documento fiscal eletronico"
        )
        canvas.save()
        return output.getvalue()

    @staticmethod
    def _header(
        canvas: Canvas, document: FiscalDocument, title: str, width: float, height: float
    ) -> None:
        canvas.setStrokeColor(colors.black)
        canvas.rect(10 * mm, height - 45 * mm, width - 20 * mm, 35 * mm)
        canvas.setFont("Helvetica-Bold", 18)
        canvas.drawString(15 * mm, height - 20 * mm, title)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(15 * mm, height - 27 * mm, f"Modelo {document.model.value}")
        canvas.drawString(
            15 * mm, height - 32 * mm, f"Serie {document.series}  Numero {document.number}"
        )
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(75 * mm, height - 19 * mm, document.issuer.legal_name[:75])
        canvas.setFont("Helvetica", 8)
        canvas.drawString(75 * mm, height - 25 * mm, f"CNPJ/CPF: {document.issuer.tax_id}")
        canvas.drawString(75 * mm, height - 30 * mm, _address(document.issuer))

    @staticmethod
    def _parties(canvas: Canvas, document: FiscalDocument, y: float, width: float) -> float:
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(10 * mm, y, "DESTINATARIO")
        canvas.setFont("Helvetica", 8)
        canvas.drawString(10 * mm, y - 5 * mm, document.recipient.legal_name[:95])
        canvas.drawString(10 * mm, y - 10 * mm, f"CNPJ/CPF: {document.recipient.tax_id}")
        canvas.drawString(70 * mm, y - 10 * mm, _address(document.recipient)[:90])
        canvas.line(10 * mm, y - 14 * mm, width - 10 * mm, y - 14 * mm)
        return float(y - 22 * mm)

    @staticmethod
    def _items(canvas: Canvas, document: FiscalDocument, y: float, width: float) -> float:
        canvas.setFont("Helvetica-Bold", 7)
        columns = (10, 35, 105, 130, 152, 175)
        labels = ("CODIGO", "DESCRICAO", "NCM", "QTD", "V.UNIT", "V.TOTAL")
        for x, label in zip(columns, labels, strict=True):
            canvas.drawString(x * mm, y, label)
        y -= 4 * mm
        canvas.line(10 * mm, y, width - 10 * mm, y)
        y -= 4 * mm
        canvas.setFont("Helvetica", 7)
        for item in document.items:
            if y < 35 * mm:
                canvas.showPage()
                y = A4[1] - 20 * mm
                canvas.setFont("Helvetica", 7)
            values = (
                item.code[:14],
                _fit(item.description, 64, 7, 67 * mm),
                item.ncm,
                f"{item.quantity:f}",
                f"{item.unit_price:.2f}",
                f"{item.total_amount:.2f}",
            )
            for x, value in zip(columns, values, strict=True):
                canvas.drawString(x * mm, y, value)
            y -= 4.5 * mm
        canvas.line(10 * mm, y, width - 10 * mm, y)
        return float(y - 8 * mm)

    @staticmethod
    def _totals(canvas: Canvas, document: FiscalDocument, y: float, width: float) -> None:
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawRightString(
            width - 10 * mm, y, f"Produtos: R$ {document.totals.products_amount:.2f}"
        )
        canvas.drawRightString(
            width - 10 * mm, y - 5 * mm, f"Impostos: R$ {document.totals.tax_amount:.2f}"
        )
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawRightString(
            width - 10 * mm, y - 12 * mm, f"TOTAL: R$ {document.totals.total_amount:.2f}"
        )

    def _identifiers(self, canvas: Canvas, document: FiscalDocument, width: float) -> None:
        if document.access_key is None:
            canvas.setFont("Helvetica", 8)
            canvas.drawString(10 * mm, 25 * mm, "Chave de acesso indisponivel")
            return
        key = str(document.access_key)
        barcode = code128.Code128(key, barHeight=12 * mm, barWidth=0.24 * mm)
        barcode.drawOn(canvas, 10 * mm, 22 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(10 * mm, 18 * mm, _group_key(key))
        if document.model is FiscalDocumentModel.NFCE:
            qr = QrCodeWidget(f"{self._nfce_query_url}?p={key}")
            bounds = qr.getBounds()
            drawing = Drawing(
                30 * mm,
                30 * mm,
                transform=[
                    30 * mm / (bounds[2] - bounds[0]),
                    0,
                    0,
                    30 * mm / (bounds[3] - bounds[1]),
                    0,
                    0,
                ],
            )
            drawing.add(qr)
            drawing.drawOn(canvas, width - 42 * mm, 17 * mm)

    @staticmethod
    def _watermark(document: FiscalDocument, contingency: bool) -> str | None:
        if document.status is FiscalDocumentStatus.CANCELLED:
            return "CANCELADA"
        if document.status is FiscalDocumentStatus.DRAFT:
            return "SEM VALOR FISCAL - RASCUNHO"
        if contingency:
            return "EM CONTINGENCIA"
        if document.status is not FiscalDocumentStatus.AUTHORIZED:
            return "SEM VALOR FISCAL"
        return None

    @staticmethod
    def _draw_watermark(canvas: Canvas, value: str, width: float, height: float) -> None:
        canvas.saveState()
        canvas.setFillColor(colors.Color(0.75, 0.1, 0.1, alpha=0.18))
        canvas.translate(width / 2, height / 2)
        canvas.rotate(35)
        canvas.setFont("Helvetica-Bold", 30)
        canvas.drawCentredString(0, 0, value)
        canvas.restoreState()


class FiscalXmlPackager:
    def authorized(self, document: FiscalDocument) -> bytes:
        if document.status not in {FiscalDocumentStatus.AUTHORIZED, FiscalDocumentStatus.CANCELLED}:
            raise _document_not_exportable()
        if (
            document.authorized_xml is None
            or document.access_key is None
            or document.authorization_protocol is None
            or document.authorized_at is None
        ):
            raise _document_not_exportable()
        root = fromstring(document.authorized_xml.encode("utf-8"))
        if _local_name(root.tag) == "nfeProc":
            return cast(bytes, ET.tostring(root, encoding="utf-8", xml_declaration=True))
        package = ET.Element(f"{{{NFE_NAMESPACE}}}nfeProc", {"versao": "4.00"})
        package.append(root)
        protocol = ET.SubElement(package, f"{{{NFE_NAMESPACE}}}protNFe", {"versao": "4.00"})
        info = ET.SubElement(protocol, f"{{{NFE_NAMESPACE}}}infProt")
        _child(info, "chNFe", str(document.access_key))
        _child(info, "dhRecbto", document.authorized_at.isoformat())
        _child(info, "nProt", document.authorization_protocol)
        _child(info, "cStat", "100")
        _child(info, "xMotivo", "Autorizado o uso da NF-e")
        return cast(bytes, ET.tostring(package, encoding="utf-8", xml_declaration=True))

    def cancellation(self, document: FiscalDocument) -> bytes:
        if (
            document.status is not FiscalDocumentStatus.CANCELLED
            or document.cancellation_xml is None
        ):
            raise _document_not_exportable()
        root = fromstring(document.cancellation_xml.encode("utf-8"))
        if _local_name(root.tag) == "procEventoNFe":
            return cast(bytes, ET.tostring(root, encoding="utf-8", xml_declaration=True))
        package = ET.Element(f"{{{NFE_NAMESPACE}}}procEventoNFe", {"versao": "1.00"})
        package.append(root)
        response = ET.SubElement(package, f"{{{NFE_NAMESPACE}}}retEvento", {"versao": "1.00"})
        info = ET.SubElement(response, f"{{{NFE_NAMESPACE}}}infEvento")
        _child(info, "tpEvento", "110111")
        _child(info, "chNFe", str(document.access_key))
        _child(info, "nProt", document.cancellation_protocol or "")
        _child(info, "cStat", "135")
        _child(info, "xMotivo", "Evento registrado e vinculado a NF-e")
        return cast(bytes, ET.tostring(package, encoding="utf-8", xml_declaration=True))


class FiscalDocumentStorageService:
    def __init__(
        self,
        documents: FiscalDocumentService,
        storage: FiscalArtifactStoragePort,
        *,
        danfe: DanfeGenerator | None = None,
        xml: FiscalXmlPackager | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._documents = documents
        self._storage = storage
        self._danfe = danfe or DanfeGenerator()
        self._xml = xml or FiscalXmlPackager()
        self._now = now or (lambda: datetime.now(UTC))

    async def danfe(
        self, context: SecurityContext, company_id: UUID, document_id: UUID
    ) -> FiscalArtifact:
        document = await self._documents.get(context, company_id, document_id)
        content = self._danfe.generate(document, contingency=_is_contingency(document))
        filename = f"{'DANFE' if document.model is FiscalDocumentModel.NFE else 'DANFCE'}-{_identity(document)}.pdf"
        return await self._store(document, content, PDF_CONTENT_TYPE, filename)

    async def xml(
        self, context: SecurityContext, company_id: UUID, document_id: UUID
    ) -> FiscalArtifact:
        document = await self._documents.get(context, company_id, document_id)
        if document.status is FiscalDocumentStatus.CANCELLED:
            content = self._xml.cancellation(document)
            filename = f"procEventoNFe-{_identity(document)}.xml"
        else:
            content = self._xml.authorized(document)
            filename = f"procNFe-{_identity(document)}.xml"
        return await self._store(document, content, XML_CONTENT_TYPE, filename)

    async def _store(
        self, document: FiscalDocument, content: bytes, content_type: str, filename: str
    ) -> FiscalArtifact:
        reference = document.cancelled_at or document.authorized_at or self._now()
        key = (
            f"fiscal/{document.company_id}/{reference:%Y/%m}/{document.model.value}/"
            f"{document.id}/v{document.version}/{filename}"
        )
        if await self._storage.exists(key):
            persisted = await self._storage.get(key)
            return FiscalArtifact(
                persisted,
                content_type,
                filename,
                key,
                hashlib.sha256(persisted).hexdigest(),
            )
        stored = await self._storage.put(key, content, content_type=content_type)
        return FiscalArtifact(content, content_type, filename, stored.key, stored.sha256)


def _address(party: FiscalPartySnapshot) -> str:
    return f"{party.street}, {party.number} - {party.district} - {party.city}/{party.state_code}"


def _fit(value: str, max_chars: int, font_size: int, width: float) -> str:
    text = value[:max_chars]
    while text and stringWidth(text, "Helvetica", font_size) > width:
        text = text[:-1]
    return text


def _group_key(value: str) -> str:
    return " ".join(value[index : index + 4] for index in range(0, len(value), 4))


def _identity(document: FiscalDocument) -> str:
    return (
        str(document.access_key)
        if document.access_key is not None
        else f"{document.model.value}-{document.series}-{document.number}"
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(parent: ET.Element, name: str, value: str) -> None:
    ET.SubElement(parent, f"{{{NFE_NAMESPACE}}}{name}").text = value


def _is_contingency(document: FiscalDocument) -> bool:
    return any("conting" in response.message.casefold() for response in document.sefaz_history)


def _document_not_exportable() -> ApplicationError:
    return ApplicationError(
        code="FISCAL_DOCUMENT_NOT_EXPORTABLE",
        message="Only authorized fiscal documents have an official XML package.",
        status_code=409,
    )


__all__ = [
    "PDF_CONTENT_TYPE",
    "XML_CONTENT_TYPE",
    "DanfeGenerator",
    "FiscalArtifact",
    "FiscalArtifactStoragePort",
    "FiscalDocumentStorageService",
    "FiscalXmlPackager",
]
