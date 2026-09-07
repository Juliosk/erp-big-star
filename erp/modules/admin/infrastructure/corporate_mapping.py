"""Mappings between M1 corporate persistence rows and domain aggregates."""

from erp.modules.admin.domain import Branch, Cnpj, Company, CorporateStatus, EconomicGroup
from erp.modules.admin.infrastructure.corporate_models import (
    BranchModel,
    CompanyModel,
    EconomicGroupModel,
)


def economic_group_from_model(model: EconomicGroupModel) -> EconomicGroup:
    return EconomicGroup(
        id=model.id,
        code=model.code,
        name=model.name,
        status=CorporateStatus(model.status),
        version=model.version,
    )


def company_from_model(model: CompanyModel) -> Company:
    return Company(
        id=model.id,
        group_id=model.group_id,
        code=model.code,
        legal_name=model.legal_name,
        trade_name=model.trade_name,
        tax_id=Cnpj(model.tax_id),
        timezone=model.timezone,
        status=CorporateStatus(model.status),
        version=model.version,
    )


def branch_from_model(model: BranchModel) -> Branch:
    return Branch(
        id=model.id,
        company_id=model.company_id,
        code=model.code,
        name=model.name,
        tax_id=Cnpj(model.tax_id),
        timezone=model.timezone,
        status=CorporateStatus(model.status),
        version=model.version,
    )


__all__ = ["branch_from_model", "company_from_model", "economic_group_from_model"]
