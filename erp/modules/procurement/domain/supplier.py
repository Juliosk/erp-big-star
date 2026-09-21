"""Supplier aggregate root owned by M6 Procurement."""

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.procurement.domain.exceptions import (
    DuplicateSupplierSiteError,
    InvalidSupplierDataError,
    InvalidSupplierIdentityError,
    InvalidSupplierTransitionError,
)
from erp.modules.procurement.domain.identity import (
    SupplierIdentityKind,
    SupplierTaxIdentity,
)
from erp.modules.procurement.domain.site import SupplierSite


class SupplierKind(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    COMPANY = "COMPANY"
    FOREIGN = "FOREIGN"


class SupplierStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class Supplier:
    id: UUID
    company_id: UUID
    kind: SupplierKind
    tax_identity: SupplierTaxIdentity
    legal_name: str
    trade_name: str | None
    status: SupplierStatus
    sites: tuple[SupplierSite, ...]
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or not isinstance(self.company_id, UUID):
            raise InvalidSupplierDataError("supplier identity and company scope must be UUIDs.")
        if not isinstance(self.kind, SupplierKind):
            raise InvalidSupplierDataError("kind must be an official M6 supplier kind.")
        if not isinstance(self.tax_identity, SupplierTaxIdentity):
            raise InvalidSupplierIdentityError("tax_identity must be validated by M6.")
        expected = {
            SupplierKind.INDIVIDUAL: SupplierIdentityKind.CPF,
            SupplierKind.COMPANY: SupplierIdentityKind.CNPJ,
            SupplierKind.FOREIGN: SupplierIdentityKind.FOREIGN_REGISTRATION,
        }
        if self.tax_identity.kind is not expected[self.kind]:
            raise InvalidSupplierIdentityError("supplier kind and fiscal identity are incompatible.")
        _name(self.legal_name, "legal_name")
        if self.trade_name is not None:
            _name(self.trade_name, "trade_name")
        if not isinstance(self.status, SupplierStatus):
            raise InvalidSupplierDataError("status must be an official M6 supplier status.")
        if type(self.version) is not int or self.version < 1:
            raise InvalidSupplierDataError("version must be a positive integer.")
        _validate_sites(self.id, self.company_id, self.sites)

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        kind: SupplierKind,
        identity_kind: SupplierIdentityKind,
        identity_value: str,
        identity_country_code: str,
        legal_name: str,
        trade_name: str | None = None,
    ) -> Supplier:
        return cls(
            id=uuid4(),
            company_id=company_id,
            kind=kind,
            tax_identity=SupplierTaxIdentity(
                identity_kind, identity_value, identity_country_code
            ),
            legal_name=legal_name.strip(),
            trade_name=trade_name.strip() if trade_name is not None else None,
            status=SupplierStatus.ACTIVE,
            sites=(),
            version=1,
        )

    def update_master(self, *, legal_name: str, trade_name: str | None) -> Supplier:
        candidate = replace(
            self,
            legal_name=legal_name.strip(),
            trade_name=trade_name.strip() if trade_name is not None else None,
        )
        return self if candidate == self else replace(candidate, version=self.version + 1)

    def transition_status(self, target: SupplierStatus) -> Supplier:
        if not isinstance(target, SupplierStatus):
            raise InvalidSupplierTransitionError("target must be an official M6 supplier status.")
        if target is self.status:
            return self
        allowed = {
            SupplierStatus.ACTIVE: {SupplierStatus.INACTIVE, SupplierStatus.BLOCKED},
            SupplierStatus.INACTIVE: {SupplierStatus.ACTIVE, SupplierStatus.BLOCKED},
            SupplierStatus.BLOCKED: {SupplierStatus.ACTIVE},
        }
        if target not in allowed[self.status]:
            raise InvalidSupplierTransitionError("supplier status transition is not allowed.")
        return replace(self, status=target, version=self.version + 1)

    def add_site(self, site: SupplierSite) -> Supplier:
        if not isinstance(site, SupplierSite):
            raise InvalidSupplierDataError("site must be a validated SupplierSite.")
        if site.company_id != self.company_id or site.supplier_id != self.id:
            raise InvalidSupplierDataError("site must belong to the supplier company and aggregate.")
        if any(existing.id == site.id or existing.code == site.code for existing in self.sites):
            raise DuplicateSupplierSiteError("supplier site id or code already exists.")
        if site.is_primary and any(existing.is_primary for existing in self.sites):
            raise DuplicateSupplierSiteError("supplier can have only one primary site.")
        return replace(self, sites=(*self.sites, site), version=self.version + 1)


def _name(value: str, field: str) -> None:
    if not 1 <= len(value) <= 200 or value != value.strip():
        raise InvalidSupplierDataError(f"{field} must contain 1 to 200 trimmed characters.")


def _validate_sites(supplier_id: UUID, company_id: UUID, sites: tuple[SupplierSite, ...]) -> None:
    if not isinstance(sites, tuple) or any(not isinstance(site, SupplierSite) for site in sites):
        raise InvalidSupplierDataError("sites must be a tuple of SupplierSite entities.")
    if any(site.supplier_id != supplier_id or site.company_id != company_id for site in sites):
        raise InvalidSupplierDataError("all sites must belong to the supplier aggregate.")
    codes = [site.code for site in sites]
    ids = [site.id for site in sites]
    if len(codes) != len(set(codes)) or len(ids) != len(set(ids)):
        raise DuplicateSupplierSiteError("supplier sites must have unique ids and codes.")
    if sum(site.is_primary for site in sites) > 1:
        raise DuplicateSupplierSiteError("supplier can have only one primary site.")


__all__ = ["Supplier", "SupplierKind", "SupplierStatus"]
