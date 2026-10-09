"""Inbound NF-e parsing and recipient-manifestation orchestration."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from erp.modules.fiscal.application.sefaz import (
    SefazEndpoint,
    SefazGatewayPort,
    SefazManifestationRequest,
)
from erp.modules.fiscal.contracts import InboundPurchaseMatchReference
from erp.modules.fiscal.domain import (
    FiscalDocumentModel,
    InboundFiscalDocument,
    InboundFiscalItem,
    InboundFiscalParty,
    InvalidInboundFiscalDocumentError,
    InvalidManifestationError,
    NFeAccessKey,
    RecipientManifestation,
    RecipientManifestationType,
)
from erp.platform.errors import ApplicationError, ErrorDetail

_NFE_NAMESPACE = "http://www.portalfiscal.inf.br/nfe"
_NS = {"nfe": _NFE_NAMESPACE}
_MAX_XML_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ManifestInboundDocument:
    company_id: UUID
    document_id: UUID
    expected_version: int
    event_type: RecipientManifestationType
    endpoint: SefazEndpoint
    reason: str | None = None


class InboundFiscalDocumentStore(Protocol):
    async def create(self, document: InboundFiscalDocument) -> InboundFiscalDocument: ...

    async def get(self, company_id: UUID, document_id: UUID) -> InboundFiscalDocument | None: ...

    async def save(
        self, document: InboundFiscalDocument, *, expected_version: int
    ) -> InboundFiscalDocument: ...


class InboundNFeParser:
    """Strict, side-effect-free mapper from authorized nfeProc XML to M11 VOs."""

    def parse(self, company_id: UUID, payload: bytes | str) -> InboundFiscalDocument:
        raw = payload.encode() if isinstance(payload, str) else payload
        if not raw or len(raw) > _MAX_XML_BYTES:
            raise _invalid("Inbound XML is empty or exceeds the 5 MiB limit.")
        try:
            root = ElementTree.fromstring(raw)
        except (ElementTree.ParseError, ValueError) as error:
            raise _invalid("Inbound XML is malformed or unsafe.") from error
        if root.tag != f"{{{_NFE_NAMESPACE}}}nfeProc" or root.attrib.get("versao") != "4.00":
            raise _invalid("Expected an NF-e 4.00 nfeProc document.")
        info = _required_element(root, "nfe:NFe/nfe:infNFe")
        protocol = _required_element(root, "nfe:protNFe/nfe:infProt")
        if info.attrib.get("versao") != "4.00" or _text(protocol, "nfe:cStat") != "100":
            raise _invalid("Inbound NF-e must contain an authorized 4.00 protocol.")
        key_value = _text(protocol, "nfe:chNFe")
        if info.attrib.get("Id") != f"NFe{key_value}":
            raise _invalid("NF-e access key differs between document and protocol.")
        try:
            key = NFeAccessKey(key_value)
            model = FiscalDocumentModel(_text(info, "nfe:ide/nfe:mod"))
            issued_at = datetime.fromisoformat(
                _text(info, "nfe:ide/nfe:dhEmi").replace("Z", "+00:00")
            )
            items = tuple(self._item(node) for node in info.findall("nfe:det", _NS))
            totals = _required_element(info, "nfe:total/nfe:ICMSTot")
            return InboundFiscalDocument.create(
                company_id=company_id,
                access_key=key,
                model=model,
                series=int(_text(info, "nfe:ide/nfe:serie")),
                number=int(_text(info, "nfe:ide/nfe:nNF")),
                issued_at=issued_at,
                authorization_protocol=_text(protocol, "nfe:nProt"),
                supplier=self._party(_required_element(info, "nfe:emit")),
                recipient=self._party(_required_element(info, "nfe:dest")),
                items=items,
                products_amount=_decimal(totals, "nfe:vProd"),
                total_amount=_decimal(totals, "nfe:vNF"),
                source_xml=raw.decode("utf-8"),
            )
        except (KeyError, ValueError, UnicodeDecodeError) as error:
            if isinstance(error, InvalidInboundFiscalDocumentError):
                raise
            raise _invalid(str(error)) from error

    def _party(self, node: Element) -> InboundFiscalParty:
        tax_id_node = node.find("nfe:CNPJ", _NS)
        if tax_id_node is None:
            tax_id_node = node.find("nfe:CPF", _NS)
        address = node.find("nfe:enderEmit", _NS)
        if address is None:
            address = node.find("nfe:enderDest", _NS)
        if tax_id_node is None or tax_id_node.text is None or address is None:
            raise _invalid("Inbound fiscal party is incomplete.")
        return InboundFiscalParty(
            tax_id_node.text,
            _text(node, "nfe:xNome"),
            _text(address, "nfe:UF"),
        )

    def _item(self, node: Element) -> InboundFiscalItem:
        product = _required_element(node, "nfe:prod")
        return InboundFiscalItem(
            line_number=int(node.attrib.get("nItem", "0")),
            supplier_code=_text(product, "nfe:cProd"),
            description=_text(product, "nfe:xProd"),
            ncm=_text(product, "nfe:NCM"),
            cfop=_text(product, "nfe:CFOP"),
            unit_of_measure=_text(product, "nfe:uCom"),
            quantity=_decimal(product, "nfe:qCom"),
            unit_price=_decimal(product, "nfe:vUnCom"),
            total_amount=_decimal(product, "nfe:vProd"),
        )


class InboundFiscalService:
    def __init__(
        self,
        store: InboundFiscalDocumentStore,
        gateway: SefazGatewayPort,
        parser: InboundNFeParser | None = None,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._parser = parser or InboundNFeParser()

    async def ingest(self, company_id: UUID, payload: bytes | str) -> InboundFiscalDocument:
        return await self._store.create(self._parser.parse(company_id, payload))

    async def manifest(self, command: ManifestInboundDocument) -> InboundFiscalDocument:
        document = await self._store.get(command.company_id, command.document_id)
        if document is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Inbound fiscal document not found.",
                status_code=404,
            )
        if document.version != command.expected_version:
            raise ApplicationError(
                code="VERSION_CONFLICT",
                message="The inbound fiscal document changed in another transaction.",
                status_code=409,
            )
        try:
            sequence = document.next_manifestation_sequence(command.event_type, command.reason)
        except InvalidManifestationError as error:
            raise _manifestation_error(error) from error
        result = await self._gateway.manifest_recipient(
            SefazManifestationRequest(
                access_key=document.access_key,
                event_type=command.event_type,
                event_sequence=sequence,
                endpoint=command.endpoint,
                recipient_tax_id=document.recipient.tax_id,
                reason=command.reason,
            )
        )
        if not result.accepted or result.protocol is None or result.registered_at is None:
            raise ApplicationError(
                code="FISCAL_MANIFESTATION_REJECTED",
                message=result.message,
                status_code=409,
            )
        updated = document.register_manifestation(
            RecipientManifestation(
                event_type=command.event_type,
                sequence=sequence,
                registered_at=result.registered_at,
                protocol=result.protocol,
                status_code=result.status_code,
                reason=command.reason,
                event_xml=result.event_xml,
            )
        )
        return await self._store.save(updated, expected_version=command.expected_version)


def purchase_match_reference(
    document: InboundFiscalDocument,
    *,
    purchase_order_id: UUID,
    goods_receipt_id: UUID | None = None,
) -> InboundPurchaseMatchReference:
    return InboundPurchaseMatchReference(
        company_id=document.company_id,
        inbound_fiscal_document_id=document.id,
        purchase_order_id=purchase_order_id,
        goods_receipt_id=goods_receipt_id,
        supplier_tax_id=document.supplier.tax_id,
        access_key=document.access_key,
        total_amount=document.total_amount,
    )


def _required_element(node: Element, path: str) -> Element:
    element = node.find(path, _NS)
    if element is None:
        raise _invalid(f"Required NF-e element is missing: {path}.")
    return element


def _text(node: Element, path: str) -> str:
    element = node.find(path, _NS)
    if element is None or element.text is None or not element.text.strip():
        raise _invalid(f"Required NF-e value is missing: {path}.")
    return element.text.strip()


def _decimal(node: Element, path: str) -> Decimal:
    try:
        return Decimal(_text(node, path))
    except InvalidOperation as error:
        raise _invalid(f"Invalid decimal NF-e value: {path}.") from error


def _invalid(message: str) -> InvalidInboundFiscalDocumentError:
    return InvalidInboundFiscalDocumentError(message)


def _manifestation_error(error: InvalidManifestationError) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid recipient manifestation.",
        status_code=422,
        details=[ErrorDetail(message=str(error))],
    )


__all__ = [
    "InboundFiscalDocumentStore",
    "InboundFiscalService",
    "InboundNFeParser",
    "ManifestInboundDocument",
    "purchase_match_reference",
]
