"""Supplier fiscal identity invariants."""

import pytest

from erp.modules.procurement.domain import (
    InvalidSupplierIdentityError,
    SupplierIdentityKind,
    SupplierTaxIdentity,
)


def test_brazilian_identity_normalizes_and_validates_cpf_cnpj() -> None:
    cpf = SupplierTaxIdentity(SupplierIdentityKind.CPF, "529.982.247-25", "br")
    cnpj = SupplierTaxIdentity(SupplierIdentityKind.CNPJ, "11.222.333/0001-81", "BR")

    assert cpf.value == "52998224725"
    assert cpf.country_code == "BR"
    assert cpf.reference == "CPF:BR:***4725"
    assert cnpj.value == "11222333000181"
    assert cnpj.reference == "CNPJ:BR:***0181"


@pytest.mark.parametrize(
    ("kind", "value", "country", "message"),
    [
        (SupplierIdentityKind.CPF, "111.111.111-11", "BR", "valid CPF/CNPJ"),
        (SupplierIdentityKind.CNPJ, "11.222.333/0001-82", "BR", "valid CPF/CNPJ"),
        (SupplierIdentityKind.CNPJ, "11.111.111/1111-11", "BR", "valid CPF/CNPJ"),
        (SupplierIdentityKind.CPF, "52998224725", "US", "country BR"),
        (SupplierIdentityKind.CNPJ, "<script>", "BR", "valid CPF/CNPJ"),
        (SupplierIdentityKind.FOREIGN_REGISTRATION, "US-9981", "BR", "other than BR"),
        (SupplierIdentityKind.FOREIGN_REGISTRATION, "?", "US", "2 to 60"),
    ],
)
def test_rejects_invalid_or_incompatible_fiscal_identity(
    kind: SupplierIdentityKind, value: str, country: str, message: str
) -> None:
    with pytest.raises(InvalidSupplierIdentityError, match=message):
        SupplierTaxIdentity(kind, value, country)


def test_foreign_registration_preserves_safe_canonical_reference() -> None:
    identity = SupplierTaxIdentity(
        SupplierIdentityKind.FOREIGN_REGISTRATION,
        " de 123-45.678 ",
        "de",
    )

    assert identity.value == "DE 123-45.678"
    assert identity.country_code == "DE"
    assert identity.reference == "FOREIGN_REGISTRATION:DE:***.678"


def test_identity_rejects_invalid_kind_and_country_code() -> None:
    with pytest.raises(InvalidSupplierIdentityError, match="kind"):
        SupplierTaxIdentity("CPF", "52998224725", "BR")  # type: ignore[arg-type]
    with pytest.raises(InvalidSupplierIdentityError, match="ISO"):
        SupplierTaxIdentity(SupplierIdentityKind.CPF, "52998224725", "BRA")
