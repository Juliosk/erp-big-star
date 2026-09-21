"""Supplier site, address and contact invariants."""

from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

import pytest

from erp.modules.procurement.domain import (
    InvalidSupplierDataError,
    SupplierAddress,
    SupplierSite,
)


def test_brazilian_site_normalizes_address_email_phone_and_code() -> None:
    address = SupplierAddress.create(
        line1=" Rua Industrial, 100 ",
        line2=" Galpao 2 ",
        district=" Centro ",
        city=" Sao Paulo ",
        state="sp",
        postal_code="01234-567",
        country_code="br",
    )
    site = SupplierSite.create(
        company_id=uuid4(),
        supplier_id=uuid4(),
        code=" matriz_sp ",
        name=" Matriz Sao Paulo ",
        address=address,
        email=" COMPRAS@FORNECEDOR.COM ",
        phone=" +55 (11) 99999-9999 ",
        is_primary=True,
    )

    assert address.state == "SP"
    assert address.postal_code == "01234567"
    assert site.code == "MATRIZ_SP"
    assert site.email == "compras@fornecedor.com"
    assert site.phone == "+55 (11) 99999-9999"
    assert site.active is True
    assert site.deactivate().active is False
    assert site.deactivate().activate().active is True


def test_foreign_site_accepts_non_brazilian_address_rules() -> None:
    address = SupplierAddress.create(
        line1="1600 Amphitheatre Parkway",
        city="Mountain View",
        state="California",
        postal_code="CA 94043",
        country_code="US",
    )

    assert address.country_code == "US"
    assert address.state == "CALIFORNIA"
    assert address.postal_code == "CA 94043"

    minimal = SupplierAddress.create(
        line1="Unter den Linden 1",
        city="Berlin",
        country_code="DE",
    )
    assert minimal.state is None
    assert minimal.postal_code is None


def test_foreign_address_rejects_unsafe_postal_code() -> None:
    with pytest.raises(InvalidSupplierDataError, match="foreign postal_code"):
        SupplierAddress.create(
            line1="Main Street",
            city="London",
            country_code="GB",
            postal_code="?",
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"line1": ""}, "line1"),
        ({"city": ""}, "city"),
        ({"country_code": "BRA"}, "ISO"),
        ({"state": None}, "state"),
        ({"postal_code": "123"}, "postal code"),
    ],
)
def test_brazilian_address_rejects_invalid_snapshots(
    changes: dict[str, object], message: str
) -> None:
    address = SupplierAddress.create(
        line1="Rua Um",
        city="Sao Paulo",
        state="SP",
        postal_code="01234567",
        country_code="BR",
    )
    with pytest.raises(InvalidSupplierDataError, match=message):
        cast(Any, replace)(address, **changes)


@pytest.mark.parametrize(
    ("email", "phone", "message"),
    [
        ("invalid", None, "e-mail"),
        (None, "letters", "phone"),
    ],
)
def test_site_rejects_invalid_contacts(
    email: str | None, phone: str | None, message: str
) -> None:
    with pytest.raises(InvalidSupplierDataError, match=message):
        SupplierSite.create(
            company_id=uuid4(),
            supplier_id=uuid4(),
            code="SITE",
            name="Supplier site",
            address=SupplierAddress.create(
                line1="Rua Um",
                city="Sao Paulo",
                state="SP",
                postal_code="01234567",
                country_code="BR",
            ),
            email=email,
            phone=phone,
        )


def test_site_rejects_invalid_code_scope_and_flags() -> None:
    site = SupplierSite.create(
        company_id=uuid4(),
        supplier_id=uuid4(),
        code="SITE",
        name="Supplier site",
        address=SupplierAddress.create(
            line1="Rua Um",
            city="Sao Paulo",
            state="SP",
            postal_code="01234567",
            country_code="BR",
        ),
    )
    with pytest.raises(InvalidSupplierDataError, match="code"):
        replace(site, code="bad code")
    with pytest.raises(InvalidSupplierDataError, match="UUID"):
        cast(Any, replace)(site, company_id="bad")
    with pytest.raises(InvalidSupplierDataError, match="flags"):
        cast(Any, replace)(site, active=1)
    with pytest.raises(InvalidSupplierDataError, match="address"):
        cast(Any, replace)(site, address="bad")
