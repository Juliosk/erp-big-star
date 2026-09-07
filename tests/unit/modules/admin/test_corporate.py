"""Domain tests for the M1 corporate hierarchy and fiscal identity."""

from uuid import uuid4

import pytest

from erp.modules.admin.domain import Branch, Cnpj, Company, CorporateStatus, EconomicGroup

VALID_COMPANY_CNPJ = "04.252.011/0001-10"
VALID_BRANCH_CNPJ = "11.222.333/0001-81"


def test_economic_group_normalizes_business_key_and_advances_lifecycle_version() -> None:
    group = EconomicGroup.create(code="  grp_bigstar ", name=" Grupo   Big Star ")

    inactive = group.deactivate()
    active_again = inactive.activate()

    assert group.code == "GRP_BIGSTAR"
    assert group.name == "Grupo Big Star"
    assert group.status is CorporateStatus.ACTIVE
    assert inactive.status is CorporateStatus.INACTIVE
    assert inactive.version == 2
    assert active_again.status is CorporateStatus.ACTIVE
    assert active_again.version == 3


def test_company_normalizes_legal_identity_and_timezone() -> None:
    group_id = uuid4()

    company = Company.create(
        group_id=group_id,
        code="big-star",
        legal_name=" Big Star   Indústria Ltda ",
        trade_name=" Big Star ",
        tax_id=VALID_COMPANY_CNPJ,
        timezone="America/Sao_Paulo",
    )

    assert company.group_id == group_id
    assert company.code == "BIG-STAR"
    assert company.legal_name == "Big Star Indústria Ltda"
    assert company.trade_name == "Big Star"
    assert str(company.tax_id) == "04252011000110"
    assert company.timezone == "America/Sao_Paulo"


def test_branch_keeps_company_boundary_and_own_fiscal_identity() -> None:
    company_id = uuid4()

    branch = Branch.create(
        company_id=company_id,
        code="matriz",
        name="Matriz",
        tax_id=VALID_BRANCH_CNPJ,
        timezone="America/Sao_Paulo",
    )

    assert branch.company_id == company_id
    assert branch.code == "MATRIZ"
    assert branch.tax_id.formatted == "11.222.333/0001-81"
    assert branch.version == 1


@pytest.mark.parametrize(
    "invalid_cnpj",
    ["", "11.111.111/1111-11", "11.222.333/0001-80", "123", "CNPJ 04.252.011/0001-10"],
)
def test_cnpj_rejects_invalid_length_repetition_or_check_digits(invalid_cnpj: str) -> None:
    with pytest.raises(ValueError, match="valid CNPJ"):
        Cnpj(invalid_cnpj)


@pytest.mark.parametrize("invalid_code", ["x", "contains space", "áccent", "bad.code"])
def test_corporate_code_rejects_ambiguous_business_keys(invalid_code: str) -> None:
    with pytest.raises(ValueError, match="Corporate code"):
        EconomicGroup.create(code=invalid_code, name="Valid name")


def test_company_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError, match="valid IANA timezone"):
        Company.create(
            group_id=uuid4(),
            code="COMPANY",
            legal_name="Company",
            trade_name=None,
            tax_id=VALID_COMPANY_CNPJ,
            timezone="Brazil/Unknown",
        )


def test_direct_construction_cannot_bypass_version_invariant() -> None:
    with pytest.raises(ValueError, match="version must be positive"):
        EconomicGroup(
            id=uuid4(),
            code="GROUP",
            name="Group",
            status=CorporateStatus.ACTIVE,
            version=0,
        )
