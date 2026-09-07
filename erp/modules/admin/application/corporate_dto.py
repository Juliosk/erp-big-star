"""Technology-neutral corporate query results."""

from dataclasses import dataclass
from uuid import UUID

from erp.modules.admin.domain import Company, CorporateStatus


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


__all__ = ["CompanyView"]
