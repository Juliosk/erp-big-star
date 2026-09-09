"""Pure M14 customer domain rules."""

from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

import pytest

from erp.modules.customer.domain import (
    Customer,
    CustomerStatus,
    CustomerTaxId,
    CustomerType,
    TaxIdKind,
)


def test_create_individual_customer_normalizes_cpf_and_trims_names() -> None:
    customer = Customer.create(
        company_id=uuid4(),
        customer_type=CustomerType.INDIVIDUAL,
        identity_type=TaxIdKind.CPF,
        identity_value="529.982.247-25",
        legal_name=" Maria Souza ",
        trade_name="  Maria  ",
    )

    assert customer.tax_id.value == "52998224725"
    assert customer.tax_id.reference == "CPF:***4725"
    assert customer.legal_name == "Maria Souza"
    assert customer.trade_name == "Maria"
    assert customer.status is CustomerStatus.ACTIVE
    assert customer.version == 1


def test_create_company_customer_normalizes_cnpj() -> None:
    customer = Customer.create(
        company_id=uuid4(),
        customer_type=CustomerType.COMPANY,
        identity_type=TaxIdKind.CNPJ,
        identity_value="11.222.333/0001-81",
        legal_name="Big Cliente Ltda",
    )

    assert customer.tax_id.value == "11222333000181"
    assert customer.tax_id.reference == "CNPJ:***0181"
    assert customer.trade_name is None


@pytest.mark.parametrize(
    ("customer_type", "identity_type", "identity_value", "message"),
    [
        (CustomerType.INDIVIDUAL, TaxIdKind.CNPJ, "11.222.333/0001-81", "require CPF"),
        (CustomerType.COMPANY, TaxIdKind.CPF, "529.982.247-25", "require CNPJ"),
        (CustomerType.INDIVIDUAL, TaxIdKind.CPF, "111.111.111-11", "valid CPF"),
        (CustomerType.COMPANY, TaxIdKind.CNPJ, "11.222.333/0001-82", "valid CPF/CNPJ"),
    ],
)
def test_rejects_invalid_identity(
    customer_type: CustomerType, identity_type: TaxIdKind, identity_value: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Customer.create(
            company_id=uuid4(),
            customer_type=customer_type,
            identity_type=identity_type,
            identity_value=identity_value,
            legal_name="Cliente",
        )


@pytest.mark.parametrize("value", ["", " ", "X" * 201])
def test_rejects_invalid_names(value: str) -> None:
    with pytest.raises(ValueError, match="legal_name"):
        Customer.create(
            company_id=uuid4(),
            customer_type=CustomerType.INDIVIDUAL,
            identity_type=TaxIdKind.CPF,
            identity_value="52998224725",
            legal_name=value,
        )


def test_update_master_changes_only_descriptive_fields_and_versions() -> None:
    customer = Customer.create(
        company_id=uuid4(),
        customer_type=CustomerType.COMPANY,
        identity_type=TaxIdKind.CNPJ,
        identity_value="11222333000181",
        legal_name="Cliente A",
        trade_name=None,
    )

    unchanged = customer.update_master(legal_name="Cliente A", trade_name=None)
    changed = customer.update_master(legal_name="Cliente B", trade_name=" Loja ")

    assert unchanged is customer
    assert changed.version == 2
    assert changed.tax_id == customer.tax_id
    assert changed.legal_name == "Cliente B"
    assert changed.trade_name == "Loja"


def test_status_transitions_are_explicit_and_versioned() -> None:
    customer = Customer.create(
        company_id=uuid4(),
        customer_type=CustomerType.COMPANY,
        identity_type=TaxIdKind.CNPJ,
        identity_value="11222333000181",
        legal_name="Cliente A",
    )

    blocked = customer.transition_status(CustomerStatus.BLOCKED)
    released = blocked.transition_status(CustomerStatus.ACTIVE)
    inactive = released.transition_status(CustomerStatus.INACTIVE)

    assert blocked.status is CustomerStatus.BLOCKED
    assert blocked.version == 2
    assert released.status is CustomerStatus.ACTIVE
    assert released.version == 3
    assert inactive.status is CustomerStatus.INACTIVE
    assert inactive.version == 4
    assert inactive.transition_status(CustomerStatus.INACTIVE) is inactive


def test_status_transition_rejects_forbidden_target() -> None:
    customer = Customer.create(
        company_id=uuid4(),
        customer_type=CustomerType.INDIVIDUAL,
        identity_type=TaxIdKind.CPF,
        identity_value="52998224725",
        legal_name="Cliente",
    ).transition_status(CustomerStatus.BLOCKED)
    with pytest.raises(ValueError, match="not allowed"):
        customer.transition_status(CustomerStatus.INACTIVE)
    with pytest.raises(ValueError, match="target status"):
        customer.transition_status("ACTIVE")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": "invalid"}, "UUID"),
        ({"customer_type": "INVALID"}, "customer_type"),
        ({"tax_id": "invalid"}, "tax_id"),
        ({"status": "INVALID"}, "status"),
        ({"version": 0}, "version"),
        ({"trade_name": " "}, "trade_name"),
    ],
)
def test_rejects_invalid_snapshot_fields(changes: dict[str, Any], message: str) -> None:
    customer = Customer.create(
        company_id=uuid4(),
        customer_type=CustomerType.INDIVIDUAL,
        identity_type=TaxIdKind.CPF,
        identity_value="52998224725",
        legal_name="Cliente",
    )
    with pytest.raises(ValueError, match=message):
        cast(Any, replace)(customer, **changes)


def test_tax_id_rejects_forbidden_characters_and_invalid_kind() -> None:
    with pytest.raises(ValueError, match="valid CPF/CNPJ"):
        CustomerTaxId(TaxIdKind.CPF, "52998224725<script>")
    with pytest.raises(ValueError, match="identity_type"):
        CustomerTaxId("CPF", "52998224725")  # type: ignore[arg-type]
    assert str(CustomerTaxId(TaxIdKind.CPF, "52998224725")) == "52998224725"
    with pytest.raises(ValueError, match="valid CPF/CNPJ"):
        CustomerTaxId(TaxIdKind.CNPJ, "11")


def test_customer_snapshot_must_keep_trimmed_trade_name() -> None:
    customer = Customer.create(
        company_id=uuid4(),
        customer_type=CustomerType.COMPANY,
        identity_type=TaxIdKind.CNPJ,
        identity_value="11222333000181",
        legal_name="Cliente",
        trade_name="Loja",
    )
    with pytest.raises(ValueError, match="trade_name"):
        replace(customer, trade_name=" Loja ")
