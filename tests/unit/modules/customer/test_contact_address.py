"""Pure rules for M14 customer contacts and addresses."""

from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

import pytest

from erp.modules.customer.domain import (
    CustomerAddress,
    CustomerAddressRole,
    CustomerContact,
    CustomerContactKind,
    CustomerContactRole,
)


def test_contact_normalizes_email_and_accepts_phone() -> None:
    company_id, customer_id = uuid4(), uuid4()
    email = CustomerContact.create(
        company_id=company_id,
        customer_id=customer_id,
        role=CustomerContactRole.COMMERCIAL,
        kind=CustomerContactKind.EMAIL,
        value=" Pessoa@Cliente.COM ",
        name="  Maria  ",
        is_primary=True,
    )
    phone = CustomerContact.create(
        company_id=company_id,
        customer_id=customer_id,
        role=CustomerContactRole.BILLING,
        kind=CustomerContactKind.PHONE,
        value=" +55 (11) 99999-9999 ",
    )

    assert email.value == "pessoa@cliente.com"
    assert email.name == "Maria"
    assert email.is_primary is True
    assert phone.value == "+55 (11) 99999-9999"


@pytest.mark.parametrize(
    ("kind", "value", "message"),
    [
        (CustomerContactKind.EMAIL, "not-email", "e-mail"),
        (CustomerContactKind.PHONE, "abc", "phone"),
        (CustomerContactKind.EMAIL, "a@b.c", "e-mail"),
    ],
)
def test_contact_rejects_invalid_values(
    kind: CustomerContactKind, value: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        CustomerContact.create(
            company_id=uuid4(),
            customer_id=uuid4(),
            role=CustomerContactRole.FISCAL,
            kind=kind,
            value=value,
        )


def test_contact_rejects_invalid_snapshot_fields() -> None:
    contact = CustomerContact.create(
        company_id=uuid4(),
        customer_id=uuid4(),
        role=CustomerContactRole.FISCAL,
        kind=CustomerContactKind.EMAIL,
        value="fiscal@cliente.com",
    )
    with pytest.raises(ValueError, match="role"):
        cast(Any, replace)(contact, role="FISCAL")
    with pytest.raises(ValueError, match="UUID"):
        cast(Any, replace)(contact, company_id="bad")
    with pytest.raises(ValueError, match="kind"):
        cast(Any, replace)(contact, kind="EMAIL")
    with pytest.raises(ValueError, match="value"):
        cast(Any, replace)(contact, value=" duplicated@example.com ")
    with pytest.raises(ValueError, match="name"):
        cast(Any, replace)(contact, name="")
    with pytest.raises(ValueError, match="boolean"):
        cast(Any, replace)(contact, is_primary=1)


def test_address_normalizes_postal_code_and_location_codes() -> None:
    address = CustomerAddress.create(
        company_id=uuid4(),
        customer_id=uuid4(),
        role=CustomerAddressRole.SHIPPING,
        line1=" Rua Um, 100 ",
        city=" Sao Paulo ",
        state="sp",
        postal_code="01234-567",
        line2="  Sala 1 ",
        district=" Centro ",
        is_primary=True,
    )

    assert address.line1 == "Rua Um, 100"
    assert address.city == "Sao Paulo"
    assert address.state == "SP"
    assert address.postal_code == "01234567"
    assert address.country_code == "BR"
    assert address.line2 == "Sala 1"
    assert address.district == "Centro"
    assert address.is_primary is True


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"role": "BAD"}, "role"),
        ({"line1": " "}, "line1"),
        ({"city": " "}, "city"),
        ({"state": "SPO"}, "state"),
        ({"postal_code": "123"}, "postal_code"),
        ({"country_code": "BRA"}, "country_code"),
        ({"line2": " "}, "line2"),
        ({"district": " "}, "district"),
        ({"is_primary": 1}, "boolean"),
    ],
)
def test_address_rejects_invalid_snapshot_fields(changes: dict[str, object], message: str) -> None:
    address = CustomerAddress.create(
        company_id=uuid4(),
        customer_id=uuid4(),
        role=CustomerAddressRole.BILLING,
        line1="Rua Um",
        city="Sao Paulo",
        state="SP",
        postal_code="01234567",
    )
    with pytest.raises(ValueError, match="UUID"):
        cast(Any, replace)(address, customer_id="bad")
    with pytest.raises(ValueError, match=message):
        cast(Any, replace)(address, **changes)
