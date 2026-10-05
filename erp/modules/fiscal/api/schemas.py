"""M11 fiscal HTTP request and response contracts."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.fiscal.application import CreateFiscalDocument, FiscalDocumentPage
from erp.modules.fiscal.domain import (
    FiscalDocument,
    FiscalDocumentItem,
    FiscalDocumentModel,
    FiscalDocumentStatus,
    FiscalDocumentTotals,
    FiscalPartySnapshot,
    TaxComponentSnapshot,
    TaxKind,
    TaxSnapshot,
)


class FiscalPartyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tax_id: str = Field(min_length=11, max_length=18)
    legal_name: str = Field(min_length=1, max_length=200)
    state_registration: str | None = Field(default=None, max_length=32)
    street: str = Field(min_length=1, max_length=180)
    number: str = Field(min_length=1, max_length=30)
    district: str = Field(min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=120)
    state_code: str = Field(min_length=2, max_length=2)
    postal_code: str = Field(min_length=8, max_length=10)
    country_code: str = Field(default="BR", min_length=2, max_length=2)

    def to_domain(self) -> FiscalPartySnapshot:
        return FiscalPartySnapshot(**self.model_dump())


class TaxComponentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tax_code: str = Field(min_length=1, max_length=16)
    taxable_base: Decimal = Field(ge=0)
    rate: Decimal = Field(ge=0)
    amount: Decimal = Field(ge=0)

    def to_domain(self, kind: TaxKind) -> TaxComponentSnapshot:
        return TaxComponentSnapshot.create(kind=kind, **self.model_dump())


class TaxSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    icms: TaxComponentRequest
    pis: TaxComponentRequest
    cofins: TaxComponentRequest
    ipi: TaxComponentRequest

    def to_domain(self) -> TaxSnapshot:
        return TaxSnapshot(
            icms=self.icms.to_domain(TaxKind.ICMS),
            pis=self.pis.to_domain(TaxKind.PIS),
            cofins=self.cofins.to_domain(TaxKind.COFINS),
            ipi=self.ipi.to_domain(TaxKind.IPI),
        )


class FiscalItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    code: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=500)
    ncm: str = Field(min_length=1, max_length=8)
    cfop: str = Field(min_length=1, max_length=4)
    unit_of_measure: str = Field(min_length=1, max_length=8)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    freight_amount: Decimal = Field(default=Decimal("0"), ge=0)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    total_amount: Decimal | None = Field(default=None, ge=0)
    taxes: TaxSnapshotRequest

    def to_domain(self) -> FiscalDocumentItem:
        values = self.model_dump(exclude={"taxes"})
        return FiscalDocumentItem.create(**values, tax_snapshot=self.taxes.to_domain())


class FiscalTotalsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    products_amount: Decimal = Field(ge=0)
    freight_amount: Decimal = Field(ge=0)
    discount_amount: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(ge=0)
    total_amount: Decimal = Field(ge=0)

    def to_domain(self) -> FiscalDocumentTotals:
        return FiscalDocumentTotals.create(**self.model_dump())


class CreateFiscalDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    model: FiscalDocumentModel
    series: int = Field(ge=1)
    number: int = Field(ge=1)
    issuer: FiscalPartyRequest
    recipient: FiscalPartyRequest
    items: list[FiscalItemRequest] = Field(min_length=1, max_length=990)
    totals: FiscalTotalsRequest | None = None

    def to_command(self) -> CreateFiscalDocument:
        return CreateFiscalDocument(
            company_id=self.company_id,
            model=self.model,
            series=self.series,
            number=self.number,
            issuer=self.issuer.to_domain(),
            recipient=self.recipient.to_domain(),
            items=tuple(item.to_domain() for item in self.items),
            totals=None if self.totals is None else self.totals.to_domain(),
        )


class FiscalDocumentResponse(BaseModel):
    id: UUID
    company_id: UUID
    model: FiscalDocumentModel
    series: int
    number: int
    status: FiscalDocumentStatus
    issuer: dict[str, object]
    recipient: dict[str, object]
    items: list[dict[str, object]]
    totals: dict[str, Decimal]
    access_key: str | None
    authorization_protocol: str | None
    rejection_code: str | None
    rejection_reason: str | None
    authorized_at: datetime | None
    cancellation_protocol: str | None
    cancelled_at: datetime | None
    sefaz_history: list[dict[str, object]]
    version: int

    @classmethod
    def from_domain(cls, document: FiscalDocument) -> FiscalDocumentResponse:
        def party(value: FiscalPartySnapshot) -> dict[str, object]:
            return {name: getattr(value, name) for name in value.__dataclass_fields__}

        def component(value: TaxComponentSnapshot) -> dict[str, object]:
            return {
                "kind": value.kind,
                "tax_code": value.tax_code,
                "taxable_base": value.taxable_base,
                "rate": value.rate,
                "amount": value.amount,
            }

        return cls(
            id=document.id,
            company_id=document.company_id,
            model=document.model,
            series=document.series,
            number=document.number,
            status=document.status,
            issuer=party(document.issuer),
            recipient=party(document.recipient),
            items=[
                {
                    "id": item.id,
                    "product_id": item.product_id,
                    "code": item.code,
                    "description": item.description,
                    "ncm": item.ncm,
                    "cfop": item.cfop,
                    "unit_of_measure": item.unit_of_measure,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "freight_amount": item.freight_amount,
                    "discount_amount": item.discount_amount,
                    "total_amount": item.total_amount,
                    "taxes": {
                        "icms": component(item.tax_snapshot.icms),
                        "pis": component(item.tax_snapshot.pis),
                        "cofins": component(item.tax_snapshot.cofins),
                        "ipi": component(item.tax_snapshot.ipi),
                    },
                }
                for item in document.items
            ],
            totals={name: getattr(document.totals, name) for name in document.totals.__dataclass_fields__},
            access_key=None if document.access_key is None else str(document.access_key),
            authorization_protocol=document.authorization_protocol,
            rejection_code=document.rejection_code,
            rejection_reason=document.rejection_reason,
            authorized_at=document.authorized_at,
            cancellation_protocol=document.cancellation_protocol,
            cancelled_at=document.cancelled_at,
            sefaz_history=[
                {
                    "attempt_id": item.attempt_id,
                    "status_code": item.status_code,
                    "message": item.message,
                    "occurred_at": item.occurred_at,
                    "protocol": item.protocol,
                }
                for item in document.sefaz_history
            ],
            version=document.version,
        )


class PageMetadata(BaseModel):
    page: int
    page_size: int
    has_more: bool


class FiscalDocumentListResponse(BaseModel):
    data: list[FiscalDocumentResponse]
    meta: PageMetadata

    @classmethod
    def from_page(cls, page: FiscalDocumentPage) -> FiscalDocumentListResponse:
        return cls(
            data=[FiscalDocumentResponse.from_domain(item) for item in page.items],
            meta=PageMetadata(page=page.page, page_size=page.page_size, has_more=page.has_more),
        )


__all__ = [
    "CreateFiscalDocumentRequest",
    "FiscalDocumentListResponse",
    "FiscalDocumentResponse",
]
