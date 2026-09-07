"""Technology-neutral corporate query results."""

from dataclasses import dataclass
from uuid import UUID

from erp.modules.admin.domain import Branch, Company, CorporateStatus, EconomicGroup


@dataclass(frozen=True, slots=True)
class EconomicGroupView:
    id: UUID
    code: str
    name: str
    status: CorporateStatus
    version: int

    @classmethod
    def from_domain(cls, group: EconomicGroup) -> EconomicGroupView:
        return cls(
            id=group.id,
            code=group.code,
            name=group.name,
            status=group.status,
            version=group.version,
        )


@dataclass(frozen=True, slots=True)
class CompanyView:
    id: UUID
    group_id: UUID
    code: str
    legal_name: str
    trade_name: str | None
    tax_id: str
    timezone: str
    status: CorporateStatus
    version: int

    @classmethod
    def from_domain(cls, company: Company) -> CompanyView:
        return cls(
            id=company.id,
            group_id=company.group_id,
            code=company.code,
            legal_name=company.legal_name,
            trade_name=company.trade_name,
            tax_id=str(company.tax_id),
            timezone=company.timezone,
            status=company.status,
            version=company.version,
        )


@dataclass(frozen=True, slots=True)
class BranchView:
    id: UUID
    company_id: UUID
    code: str
    name: str
    tax_id: str
    timezone: str
    status: CorporateStatus
    version: int

    @classmethod
    def from_domain(cls, branch: Branch) -> BranchView:
        return cls(
            id=branch.id,
            company_id=branch.company_id,
            code=branch.code,
            name=branch.name,
            tax_id=str(branch.tax_id),
            timezone=branch.timezone,
            status=branch.status,
            version=branch.version,
        )


@dataclass(frozen=True, slots=True)
class CompanySelectorCompany:
    company: CompanyView
    branches: tuple[BranchView, ...]


@dataclass(frozen=True, slots=True)
class CompanySelectorGroup:
    group: EconomicGroupView
    companies: tuple[CompanySelectorCompany, ...]


@dataclass(frozen=True, slots=True)
class CompanySelectorView:
    groups: tuple[CompanySelectorGroup, ...]


__all__ = [
    "BranchView",
    "CompanySelectorCompany",
    "CompanySelectorGroup",
    "CompanySelectorView",
    "CompanyView",
    "EconomicGroupView",
]
