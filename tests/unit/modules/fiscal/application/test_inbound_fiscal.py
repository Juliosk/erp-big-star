"""Inbound supplier NF-e parsing, MDE transitions and SEFAZ mock orchestration."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from erp.modules.fiscal.application import (
    InboundFiscalService,
    InboundNFeParser,
    ManifestInboundDocument,
    SefazEndpoint,
    SefazEnvironment,
    purchase_match_reference,
)
from erp.modules.fiscal.domain import (
    FiscalDocumentModel,
    InboundFiscalDocument,
    InvalidInboundFiscalDocumentError,
    InvalidManifestationError,
    RecipientManifestation,
    RecipientManifestationType,
)
from erp.modules.fiscal.infrastructure import SefazMockAdapter, SefazMockScenario
from erp.platform.errors import ApplicationError
from tests.unit.modules.fiscal.domain.test_fiscal_document import access_key


def inbound_xml(*, status: str = "100", key: str | None = None) -> str:
    value = key or str(access_key())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe><infNFe Id="NFe{value}" versao="4.00">
    <ide><mod>55</mod><serie>1</serie><nNF>123</nNF><dhEmi>2026-10-09T10:00:00-03:00</dhEmi></ide>
    <emit><CNPJ>12345678000195</CNPJ><xNome>Fornecedor Exemplo</xNome><enderEmit><UF>SP</UF></enderEmit></emit>
    <dest><CNPJ>11222333000181</CNPJ><xNome>Big Star</xNome><enderDest><UF>SP</UF></enderDest></dest>
    <det nItem="1"><prod><cProd>SUP-1</cProd><xProd>Produto recebido</xProd><NCM>95030099</NCM><CFOP>5102</CFOP><uCom>UN</uCom><qCom>2.0000</qCom><vUnCom>10.00</vUnCom><vProd>20.00</vProd></prod></det>
    <total><ICMSTot><vProd>20.00</vProd><vNF>20.00</vNF></ICMSTot></total>
  </infNFe></NFe>
  <protNFe><infProt><cStat>{status}</cStat><chNFe>{value}</chNFe><nProt>135260000000001</nProt></infProt></protNFe>
</nfeProc>"""


class MemoryInboundStore:
    def __init__(self) -> None:
        self.items: dict[tuple[UUID, UUID], InboundFiscalDocument] = {}
        self.saved_expected_versions: list[int] = []

    async def create(self, document: InboundFiscalDocument) -> InboundFiscalDocument:
        self.items[(document.company_id, document.id)] = document
        return document

    async def get(self, company_id: UUID, document_id: UUID) -> InboundFiscalDocument | None:
        return self.items.get((company_id, document_id))

    async def save(
        self, document: InboundFiscalDocument, *, expected_version: int
    ) -> InboundFiscalDocument:
        self.saved_expected_versions.append(expected_version)
        self.items[(document.company_id, document.id)] = document
        return document


def parse(company_id: UUID | None = None) -> InboundFiscalDocument:
    return InboundNFeParser().parse(company_id or uuid4(), inbound_xml())


def command(
    document: InboundFiscalDocument,
    event_type: RecipientManifestationType,
    *,
    reason: str | None = None,
    version: int | None = None,
) -> ManifestInboundDocument:
    return ManifestInboundDocument(
        document.company_id,
        document.id,
        version or document.version,
        event_type,
        SefazEndpoint("SP", SefazEnvironment.HOMOLOGATION),
        reason,
    )


def test_parser_maps_authorized_supplier_nfe_proc_to_pure_model() -> None:
    company_id = uuid4()
    document = InboundNFeParser().parse(company_id, inbound_xml().encode())

    assert document.company_id == company_id
    assert str(document.access_key) == str(access_key())
    assert document.number == 123
    assert document.supplier.legal_name == "Fornecedor Exemplo"
    assert document.recipient.tax_id == "11222333000181"
    assert document.items[0].supplier_code == "SUP-1"
    assert document.items[0].quantity == Decimal("2.0000")
    assert document.products_amount == document.total_amount == Decimal("20.00")
    assert document.authorization_protocol == "135260000000001"


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "<not-xml",
        "<nfeProc/>",
        inbound_xml(status="204"),
        inbound_xml().replace("vProd>20.00", "vProd>21.00", 1),
        "<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>",
    ],
)
def test_parser_rejects_malformed_unsafe_or_inconsistent_xml(payload: str) -> None:
    with pytest.raises(InvalidInboundFiscalDocumentError):
        InboundNFeParser().parse(uuid4(), payload)


@pytest.mark.parametrize(
    ("event_type", "reason"),
    [
        (RecipientManifestationType.CONFIRMATION, None),
        (RecipientManifestationType.UNKNOWN_OPERATION, None),
        (
            RecipientManifestationType.OPERATION_NOT_PERFORMED,
            "Mercadoria não foi entregue pelo fornecedor",
        ),
    ],
)
def test_conclusive_manifestations_are_terminal(
    event_type: RecipientManifestationType, reason: str | None
) -> None:
    document = parse()
    event = RecipientManifestation(
        event_type,
        1,
        datetime.now(UTC),
        "135260000210001",
        "135",
        reason,
    )
    manifested = document.register_manifestation(event)

    assert manifested.version == 2
    assert manifested.conclusive_manifestation == event
    with pytest.raises(InvalidManifestationError):
        manifested.next_manifestation_sequence(RecipientManifestationType.ACKNOWLEDGEMENT)


def test_acknowledgement_can_precede_confirmation_but_cannot_repeat() -> None:
    document = parse()
    acknowledgement = RecipientManifestation(
        RecipientManifestationType.ACKNOWLEDGEMENT,
        1,
        datetime.now(UTC),
        "135260000210001",
        "135",
    )
    acknowledged = document.register_manifestation(acknowledgement)
    assert acknowledged.conclusive_manifestation is None
    assert acknowledged.next_manifestation_sequence(RecipientManifestationType.CONFIRMATION) == 2
    with pytest.raises(InvalidManifestationError):
        acknowledged.next_manifestation_sequence(RecipientManifestationType.ACKNOWLEDGEMENT)


def test_operation_not_performed_requires_exclusive_reason() -> None:
    document = parse()
    with pytest.raises(InvalidManifestationError):
        document.next_manifestation_sequence(
            RecipientManifestationType.OPERATION_NOT_PERFORMED, "curta"
        )
    with pytest.raises(InvalidManifestationError):
        document.next_manifestation_sequence(
            RecipientManifestationType.CONFIRMATION, "motivo não permitido"
        )


def test_service_ingests_and_persists_accepted_mock_mde_protocol() -> None:
    async def scenario() -> None:
        store = MemoryInboundStore()
        gateway = SefazMockAdapter()
        service = InboundFiscalService(store, gateway)
        document = await service.ingest(uuid4(), inbound_xml())

        result = await service.manifest(
            command(document, RecipientManifestationType.ACKNOWLEDGEMENT)
        )

        assert result.version == 2
        assert result.manifestations[0].protocol == "135260000210001"
        assert result.manifestations[0].event_xml is not None
        assert "210210" in result.manifestations[0].event_xml
        assert store.saved_expected_versions == [1]
        assert gateway.calls[0][0] == "manifest"

    asyncio.run(scenario())


def test_service_rejects_stale_missing_and_sefaz_rejected_manifestations() -> None:
    async def scenario() -> None:
        company_id = uuid4()
        missing_service = InboundFiscalService(MemoryInboundStore(), SefazMockAdapter())
        missing = ManifestInboundDocument(
            company_id,
            uuid4(),
            1,
            RecipientManifestationType.CONFIRMATION,
            SefazEndpoint("SP", SefazEnvironment.HOMOLOGATION),
        )
        with pytest.raises(ApplicationError, match="not found") as missing_error:
            await missing_service.manifest(missing)
        assert missing_error.value.code == "RESOURCE_NOT_FOUND"

        store = MemoryInboundStore()
        document = await store.create(parse(company_id))
        service = InboundFiscalService(
            store, SefazMockAdapter((SefazMockScenario.REJECTED_DUPLICATE,))
        )
        with pytest.raises(ApplicationError) as stale_error:
            await service.manifest(
                command(document, RecipientManifestationType.CONFIRMATION, version=99)
            )
        assert stale_error.value.code == "VERSION_CONFLICT"
        with pytest.raises(ApplicationError) as rejected_error:
            await service.manifest(command(document, RecipientManifestationType.CONFIRMATION))
        assert rejected_error.value.code == "FISCAL_MANIFESTATION_REJECTED"
        assert store.saved_expected_versions == []

    asyncio.run(scenario())


def test_purchase_match_contract_uses_only_ids_and_fiscal_snapshot() -> None:
    document = parse()
    purchase_order_id = uuid4()
    goods_receipt_id = uuid4()
    reference = purchase_match_reference(
        document,
        purchase_order_id=purchase_order_id,
        goods_receipt_id=goods_receipt_id,
    )

    assert reference.company_id == document.company_id
    assert reference.purchase_order_id == purchase_order_id
    assert reference.goods_receipt_id == goods_receipt_id
    assert reference.supplier_tax_id == document.supplier.tax_id


def test_domain_rejects_invalid_manifestation_record_and_mismatched_key() -> None:
    with pytest.raises(InvalidManifestationError):
        RecipientManifestation(
            RecipientManifestationType.CONFIRMATION,
            0,
            datetime.now(UTC),
            "",
            "",
        )
    original = parse()
    with pytest.raises(InvalidInboundFiscalDocumentError):
        InboundFiscalDocument.create(
            company_id=original.company_id,
            access_key=original.access_key,
            model=FiscalDocumentModel.NFCE,
            series=original.series,
            number=original.number,
            issued_at=original.issued_at,
            authorization_protocol=original.authorization_protocol,
            supplier=original.supplier,
            recipient=original.recipient,
            items=original.items,
            products_amount=original.products_amount,
            total_amount=original.total_amount,
            source_xml=original.source_xml,
        )
