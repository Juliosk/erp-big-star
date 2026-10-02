"""M6 supplier HTTP request and response contracts."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from erp.modules.procurement.application.suppliers import SupplierPage, SupplierSiteInput
from erp.modules.procurement.domain import (
    Supplier,
    SupplierIdentityKind,
    SupplierKind,
    SupplierStatus,
)


class SupplierSiteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=160)
    line1: str = Field(min_length=1, max_length=180)
    line2: str | None = Field(default=None, min_length=1, max_length=180)
    district: str | None = Field(default=None, min_length=1, max_length=120)
    city: str = Field(min_length=1, max_length=120)
    state: str | None = Field(default=None, min_length=1, max_length=80)
    postal_code: str | None = Field(default=None, min_length=2, max_length=20)
    country_code: str = Field(min_length=2, max_length=2)
    email: str | None = Field(default=None, max_length=180)
    phone: str | None = Field(default=None, max_length=32)
    is_primary: bool = False

    def to_input(self) -> SupplierSiteInput:
        return SupplierSiteInput(**self.model_dump())


class CreateSupplierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    kind: SupplierKind
    identity_kind: SupplierIdentityKind
    identity_value: str = Field(min_length=1, max_length=60)
    identity_country_code: str = Field(min_length=2, max_length=2)
    legal_name: str = Field(min_length=1, max_length=200)
    trade_name: str | None = Field(default=None, min_length=1, max_length=200)
    sites: list[SupplierSiteRequest] = Field(default_factory=list, max_length=100)


class UpdateSupplierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    legal_name: str | None = Field(default=None, min_length=1, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    status: SupplierStatus | None = None

    @model_validator(mode="after")
    def reject_invalid_nulls_and_empty_patch(self) -> Self:
        if "legal_name" in self.model_fields_set and self.legal_name is None:
            raise ValueError("legal_name cannot be null.")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status cannot be null.")
        if not self.model_fields_set:
            raise ValueError("At least one mutable field is required.")
        return self


class SupplierAddressResponse(BaseModel):
    line1: str
    line2: str | None
    district: str | None
    city: str
    state: str | None
    postal_code: str | None
    country_code: str


class SupplierSiteResponse(BaseModel):
    id: UUID
    company_id: UUID
    supplier_id: UUID
    code: str
    name: str
    address: SupplierAddressResponse
    email: str | None
    phone: str | None
    is_primary: bool
    active: bool


class SupplierResponse(BaseModel):
    id: UUID
    company_id: UUID
    kind: SupplierKind
    identity_kind: SupplierIdentityKind
    identity_value: str
    identity_country_code: str
    identity_ref: str
    legal_name: str
    trade_name: str | None
    status: SupplierStatus
    sites: list[SupplierSiteResponse]
    version: int

    @classmethod
    def from_domain(cls, supplier: Supplier) -> SupplierResponse:
        return cls(
            id=supplier.id,
            company_id=supplier.company_id,
            kind=supplier.kind,
            identity_kind=supplier.tax_identity.kind,
            identity_value=supplier.tax_identity.value,
            identity_country_code=supplier.tax_identity.country_code,
            identity_ref=supplier.tax_identity.reference,
            legal_name=supplier.legal_name,
            trade_name=supplier.trade_name,
            status=supplier.status,
            sites=[
                SupplierSiteResponse(
                    id=site.id,
                    company_id=site.company_id,
                    supplier_id=site.supplier_id,
                    code=site.code,
                    name=site.name,
                    address=SupplierAddressResponse(
                        line1=site.address.line1,
                        line2=site.address.line2,
                        district=site.address.district,
                        city=site.address.city,
                        state=site.address.state,
                        postal_code=site.address.postal_code,
                        country_code=site.address.country_code,
                    ),
                    email=site.email,
                    phone=site.phone,
                    is_primary=site.is_primary,
                    active=site.active,
                )
                for site in supplier.sites
            ],
            version=supplier.version,
        )


class PageMetadata(BaseModel):
    page: int
    page_size: int
    has_more: bool


class SupplierListResponse(BaseModel):
    data: list[SupplierResponse]
    meta: PageMetadata

    @classmethod
    def from_page(cls, page: SupplierPage) -> SupplierListResponse:
        return cls(
            data=[SupplierResponse.from_domain(item) for item in page.items],
            meta=PageMetadata(page=page.page, page_size=page.page_size, has_more=page.has_more),
        )


__all__ = [
    "CreateSupplierRequest",
    "SupplierListResponse",
    "SupplierResponse",
    "SupplierSiteRequest",
    "UpdateSupplierRequest",
]
