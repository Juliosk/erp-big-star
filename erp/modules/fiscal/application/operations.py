"""Operator-facing fiscal transmission commands built on the issuance worker."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID
from xml.sax.saxutils import escape

from erp.modules.admin.contracts import SecurityContext
from erp.modules.fiscal.application.issuance import (
    CancelFiscalDocument,
    FiscalIssuanceWorker,
    FiscalWorkerMetadata,
    TransmitFiscalDocument,
)
from erp.modules.fiscal.application.permissions import (
    FISCAL_NFE_CANCEL,
    FISCAL_NFE_ISSUE,
    FiscalAuthorization,
)
from erp.modules.fiscal.application.sefaz import (
    ContingencyMode,
    SefazEndpoint,
    SefazEnvironment,
    SefazSubmissionMode,
)
from erp.modules.fiscal.domain import FiscalDocument, NFeAccessKey
from erp.platform.errors import ApplicationError

_STATE_IBGE = {
    "AC": "12",
    "AL": "27",
    "AP": "16",
    "AM": "13",
    "BA": "29",
    "CE": "23",
    "DF": "53",
    "ES": "32",
    "GO": "52",
    "MA": "21",
    "MT": "51",
    "MS": "50",
    "MG": "31",
    "PA": "15",
    "PB": "25",
    "PR": "41",
    "PE": "26",
    "PI": "22",
    "RJ": "33",
    "RN": "24",
    "RS": "43",
    "RO": "11",
    "RR": "14",
    "SC": "42",
    "SP": "35",
    "SE": "28",
    "TO": "17",
}


@dataclass(frozen=True, slots=True)
class ProcessFiscalDocument:
    company_id: UUID
    document_id: UUID
    expected_version: int
    contingency: ContingencyMode
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None


@dataclass(frozen=True, slots=True)
class CancelAuthorizedFiscalDocument:
    company_id: UUID
    document_id: UUID
    expected_version: int
    reason: str
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None


class FiscalOperationsService:
    """Small application facade for an explicitly configured SEFAZ worker."""

    def __init__(self, worker: FiscalIssuanceWorker, authorization: FiscalAuthorization) -> None:
        self._worker = worker
        self._authorization = authorization

    async def process(
        self, context: SecurityContext, command: ProcessFiscalDocument
    ) -> FiscalDocument:
        await self._authorization.require(context, command.company_id, FISCAL_NFE_ISSUE, write=True)
        document = await self._required(command.company_id, command.document_id)
        _validate_contingency(document, command.contingency)
        key = _access_key(document, command.contingency)
        return await self._worker.transmit(
            TransmitFiscalDocument(
                company_id=command.company_id,
                document_id=command.document_id,
                expected_version=command.expected_version,
                actor_id=context.principal.user_id,
                access_key=key,
                unsigned_xml=_unsigned_xml(document, key),
                reference_uri=f"#NFe{key}",
                batch_id=str(document.number).zfill(15),
                endpoint=SefazEndpoint(
                    document.issuer.state_code,
                    SefazEnvironment.HOMOLOGATION,
                    command.contingency,
                ),
                mode=SefazSubmissionMode.SYNCHRONOUS,
                metadata=_metadata(command),
            )
        )

    async def cancel(
        self, context: SecurityContext, command: CancelAuthorizedFiscalDocument
    ) -> FiscalDocument:
        await self._authorization.require(
            context, command.company_id, FISCAL_NFE_CANCEL, write=True
        )
        document = await self._required(command.company_id, command.document_id)
        return await self._worker.cancel(
            CancelFiscalDocument(
                company_id=command.company_id,
                document_id=command.document_id,
                expected_version=command.expected_version,
                actor_id=context.principal.user_id,
                reason=command.reason,
                endpoint=SefazEndpoint(document.issuer.state_code, SefazEnvironment.HOMOLOGATION),
                metadata=_metadata(command),
            )
        )

    async def _required(self, company_id: UUID, document_id: UUID) -> FiscalDocument:
        document = await self._worker.get(company_id, document_id)
        if document is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Fiscal document not found.", status_code=404
            )
        return document


def _metadata(
    command: ProcessFiscalDocument | CancelAuthorizedFiscalDocument,
) -> FiscalWorkerMetadata:
    return FiscalWorkerMetadata(
        request_id=command.request_id,
        correlation_id=command.correlation_id,
        source_ip=command.source_ip,
    )


def _validate_contingency(document: FiscalDocument, mode: ContingencyMode) -> None:
    if mode is ContingencyMode.OFFLINE_NFCE and document.model.value != "65":
        raise ApplicationError(
            code="BUSINESS_VALIDATION_ERROR",
            message="Offline contingency is restricted to NFC-e model 65.",
            status_code=422,
        )
    if mode in {ContingencyMode.SVC_AN, ContingencyMode.SVC_RS} and document.model.value != "55":
        raise ApplicationError(
            code="BUSINESS_VALIDATION_ERROR",
            message="SVC contingency is restricted to NF-e model 55.",
            status_code=422,
        )


def _access_key(document: FiscalDocument, contingency: ContingencyMode) -> NFeAccessKey:
    state = _STATE_IBGE.get(document.issuer.state_code)
    if state is None:
        raise ApplicationError(
            code="BUSINESS_VALIDATION_ERROR",
            message="Issuer state has no NF-e authorizer mapping.",
            status_code=422,
        )
    tax_id = "".join(filter(str.isdigit, document.issuer.tax_id)).zfill(14)[-14:]
    emission_type = {
        ContingencyMode.NONE: "1",
        ContingencyMode.SVC_AN: "6",
        ContingencyMode.SVC_RS: "7",
        ContingencyMode.OFFLINE_NFCE: "9",
    }[contingency]
    numeric_code = str(document.id.int % 100_000_000).zfill(8)
    body = (
        f"{state}{datetime.now(UTC):%y%m}{tax_id}{document.model.value}"
        f"{document.series:03d}{document.number:09d}{emission_type}{numeric_code}"
    )
    return NFeAccessKey(body + str(_check_digit(body)))


def _check_digit(body: str) -> int:
    weight = 2
    total = 0
    for digit in reversed(body):
        total += int(digit) * weight
        weight = 2 if weight == 9 else weight + 1
    remainder = total % 11
    return 0 if remainder in {0, 1} else 11 - remainder


def _unsigned_xml(document: FiscalDocument, key: NFeAccessKey) -> bytes:
    total = document.totals.total_amount
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<NFe xmlns="http://www.portalfiscal.inf.br/nfe">'
        f'<infNFe Id="NFe{key}" versao="4.00">'
        f"<ide><mod>{document.model.value}</mod><serie>{document.series}</serie>"
        f"<nNF>{document.number}</nNF></ide>"
        f"<emit><CNPJ>{''.join(filter(str.isdigit, document.issuer.tax_id))}</CNPJ>"
        f"<xNome>{escape(document.issuer.legal_name)}</xNome></emit>"
        f"<total><ICMSTot><vNF>{total:.2f}</vNF></ICMSTot></total>"
        "</infNFe></NFe>"
    ).encode()


__all__ = [
    "CancelAuthorizedFiscalDocument",
    "FiscalOperationsService",
    "ProcessFiscalDocument",
]
