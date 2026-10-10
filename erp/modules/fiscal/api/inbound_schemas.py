"""HTTP schemas for inbound NF-e and recipient manifestations."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.fiscal.application.inbound_documents import InboundPage
from erp.modules.fiscal.domain import InboundFiscalDocument, RecipientManifestationType


class ManifestInboundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: RecipientManifestationType
    reason: str | None = Field(default=None, max_length=255)


class InboundItemResponse(BaseModel):
    line_number: int
    supplier_code: str
    description: str
    ncm: str
    cfop: str
    unit_of_measure: str
    quantity: Decimal
    unit_price: Decimal
    total_amount: Decimal


class MdeEventResponse(BaseModel):
    event_type: RecipientManifestationType
    sequence: int
    registered_at: datetime
    protocol: str
    status_code: str
    reason: str | None
    event_xml: str | None


class InboundFiscalDocumentResponse(BaseModel):
    id: UUID
    company_id: UUID
    access_key: str
    model: str
    series: int
    number: int
    issued_at: datetime
    authorization_protocol: str
    supplier: dict[str, str]
    recipient: dict[str, str]
    items: list[InboundItemResponse]
    products_amount: Decimal
    total_amount: Decimal
    source_xml: str
    mde_status: str
    manifestations: list[MdeEventResponse]
    version: int

    @classmethod
    def from_domain(cls, value: InboundFiscalDocument) -> InboundFiscalDocumentResponse:
        return cls(
            id=value.id,
            company_id=value.company_id,
            access_key=str(value.access_key),
            model=value.model.value,
            series=value.series,
            number=value.number,
            issued_at=value.issued_at,
            authorization_protocol=value.authorization_protocol,
            supplier={
                "tax_id": value.supplier.tax_id,
                "legal_name": value.supplier.legal_name,
                "state_code": value.supplier.state_code,
            },
            recipient={
                "tax_id": value.recipient.tax_id,
                "legal_name": value.recipient.legal_name,
                "state_code": value.recipient.state_code,
            },
            items=[
                InboundItemResponse(
                    **{field: getattr(item, field) for field in InboundItemResponse.model_fields}
                )
                for item in value.items
            ],
            products_amount=value.products_amount,
            total_amount=value.total_amount,
            source_xml=value.source_xml,
            mde_status=value.manifestation_status.value,
            manifestations=[
                MdeEventResponse(
                    **{field: getattr(event, field) for field in MdeEventResponse.model_fields}
                )
                for event in value.manifestations
            ],
            version=value.version,
        )


class InboundFiscalListResponse(BaseModel):
    items: list[InboundFiscalDocumentResponse]
    page: int
    page_size: int

    @classmethod
    def from_page(cls, value: InboundPage) -> InboundFiscalListResponse:
        return cls(
            items=[InboundFiscalDocumentResponse.from_domain(item) for item in value.items],
            page=value.page,
            page_size=value.page_size,
        )


__all__ = ["InboundFiscalDocumentResponse", "InboundFiscalListResponse", "ManifestInboundRequest"]
