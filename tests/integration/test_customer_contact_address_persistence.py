"""M14 contact/address persistence stays tenant-bound."""

import asyncio
from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase

from erp.modules.customer.domain import (
    CustomerAddress,
    CustomerAddressRole,
    CustomerContact,
    CustomerContactKind,
    CustomerContactRole,
)
from erp.modules.customer.infrastructure import (
    CustomerAddressModel,
    CustomerContactModel,
    CustomerRepository,
)
from erp.modules.customer.infrastructure.contact_address_repository import (
    CustomerContactAddressRepository,
)
from erp.platform.errors import ApplicationError
from tests.integration.test_customer_persistence import customer_fixture

pytestmark = pytest.mark.integration


def test_contacts_and_addresses_round_trip_under_parent_company() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            customer = data.customer()
            await CustomerRepository(session, company_id=data.company_id).add(
                customer, actor_id=data.actor_id
            )
            repository = CustomerContactAddressRepository(session, company_id=data.company_id)
            contact = CustomerContact.create(
                company_id=data.company_id,
                customer_id=customer.id,
                role=CustomerContactRole.COMMERCIAL,
                kind=CustomerContactKind.EMAIL,
                value="vendas@cliente.com",
                name="Vendas",
                is_primary=True,
            )
            address = CustomerAddress.create(
                company_id=data.company_id,
                customer_id=customer.id,
                role=CustomerAddressRole.SHIPPING,
                line1="Rua Um, 100",
                city="Sao Paulo",
                state="SP",
                postal_code="01234567",
                district="Centro",
                is_primary=True,
            )
            await repository.add_contact(contact, actor_id=data.actor_id)
            await repository.add_address(address, actor_id=data.actor_id)

            assert await repository.list_contacts(customer.id) == (contact,)
            assert await repository.list_addresses(customer.id) == (address,)

    asyncio.run(scenario())


def test_child_records_cannot_cross_company_or_missing_parent() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            customer = data.customer()
            await CustomerRepository(session, company_id=data.company_id).add(
                customer, actor_id=data.actor_id
            )
            repository = CustomerContactAddressRepository(session, company_id=data.company_id)
            contact = CustomerContact.create(
                company_id=data.other_company_id,
                customer_id=customer.id,
                role=CustomerContactRole.FISCAL,
                kind=CustomerContactKind.EMAIL,
                value="fiscal@cliente.com",
            )
            with pytest.raises(ApplicationError) as captured:
                await repository.add_contact(contact, actor_id=data.actor_id)
            assert captured.value.code == "SCOPE_FORBIDDEN"
            with pytest.raises(ApplicationError) as missing:
                await repository.list_addresses(uuid4())
            assert missing.value.code == "RESOURCE_NOT_FOUND"
            address = CustomerAddress.create(
                company_id=data.other_company_id,
                customer_id=customer.id,
                role=CustomerAddressRole.BILLING,
                line1="Rua Um",
                city="Sao Paulo",
                state="SP",
                postal_code="01234567",
            )
            with pytest.raises(ApplicationError) as address_scope:
                await repository.add_address(address, actor_id=data.actor_id)
            assert address_scope.value.code == "SCOPE_FORBIDDEN"

    asyncio.run(scenario())


def test_duplicate_contact_is_detected_for_same_customer_only() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            first = data.customer(identity_value="52998224725")
            second = data.customer(identity_value="15350946056")
            customer_repository = CustomerRepository(session, company_id=data.company_id)
            await customer_repository.add(first, actor_id=data.actor_id)
            await customer_repository.add(second, actor_id=data.actor_id)
            repository = CustomerContactAddressRepository(session, company_id=data.company_id)
            contact = CustomerContact.create(
                company_id=data.company_id,
                customer_id=first.id,
                role=CustomerContactRole.COMMERCIAL,
                kind=CustomerContactKind.EMAIL,
                value="vendas@cliente.com",
            )
            await repository.add_contact(contact, actor_id=data.actor_id)
            async with session.begin_nested() as savepoint:
                with pytest.raises(ApplicationError) as captured:
                    await repository.add_contact(
                        replace(contact, id=uuid4()), actor_id=data.actor_id
                    )
                assert captured.value.code == "CUSTOMER_CONTACT_CONFLICT"
                await savepoint.rollback()
            await repository.add_contact(
                replace(contact, id=uuid4(), customer_id=second.id), actor_id=data.actor_id
            )

    asyncio.run(scenario())


def test_non_duplicate_contact_integrity_errors_are_not_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReferentialIntegrityError(Exception):
        sqlstate = "23503"

    class SessionStub:
        def add(self, model: object) -> None:
            assert model is not None

        async def flush(self) -> None:
            raise IntegrityError(
                statement=None,
                params=None,
                orig=ReferentialIntegrityError(),
            )

    async def require_customer(customer_id: object) -> None:
        assert customer_id is not None

    company_id = uuid4()
    repository = CustomerContactAddressRepository(cast(Any, SessionStub()), company_id=company_id)
    monkeypatch.setattr(repository, "_require_customer", require_customer)
    contact = CustomerContact.create(
        company_id=company_id,
        customer_id=uuid4(),
        role=CustomerContactRole.COMMERCIAL,
        kind=CustomerContactKind.EMAIL,
        value="vendas@cliente.com",
    )
    with pytest.raises(IntegrityError):
        asyncio.run(repository.add_contact(contact, actor_id=uuid4()))


def test_child_repository_does_not_commit_callers_transaction() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data:
            customer = data.customer()
            contact = CustomerContact.create(
                company_id=data.company_id,
                customer_id=customer.id,
                role=CustomerContactRole.BILLING,
                kind=CustomerContactKind.PHONE,
                value="+55 11 99999-9999",
            )
            async with data.database.session() as session:
                await CustomerRepository(session, company_id=data.company_id).add(
                    customer, actor_id=data.actor_id
                )
                await CustomerContactAddressRepository(
                    session, company_id=data.company_id
                ).add_contact(contact, actor_id=data.actor_id)
                await session.rollback()
            async with data.database.session() as session:
                assert (
                    await session.scalar(
                        select(CustomerContactModel.id).where(CustomerContactModel.id == contact.id)
                    )
                    is None
                )

    asyncio.run(scenario())


def test_child_repository_requires_explicit_company_and_actor_ids() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="company UUID"):
            CustomerContactAddressRepository(cast(Any, object()), company_id=cast(Any, "bad"))
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            customer = data.customer()
            await CustomerRepository(session, company_id=data.company_id).add(
                customer, actor_id=data.actor_id
            )
            repository = CustomerContactAddressRepository(session, company_id=data.company_id)
            contact = CustomerContact.create(
                company_id=data.company_id,
                customer_id=customer.id,
                role=CustomerContactRole.BILLING,
                kind=CustomerContactKind.EMAIL,
                value="financeiro@cliente.com",
            )
            address = CustomerAddress.create(
                company_id=data.company_id,
                customer_id=customer.id,
                role=CustomerAddressRole.BILLING,
                line1="Rua Um",
                city="Sao Paulo",
                state="SP",
                postal_code="01234567",
            )
            with pytest.raises(ValueError, match="actor UUID"):
                await repository.add_contact(contact, actor_id=cast(Any, "bad"))
            with pytest.raises(ValueError, match="actor UUID"):
                await repository.add_address(address, actor_id=cast(Any, "bad"))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (CustomerContactModel, "role", "BAD"),
        (CustomerContactModel, "kind", "BAD"),
        (CustomerContactModel, "value", " "),
        (CustomerContactModel, "name", " "),
        (CustomerAddressModel, "role", "BAD"),
        (CustomerAddressModel, "line1", " "),
        (CustomerAddressModel, "state", "sp"),
        (CustomerAddressModel, "postal_code", "123"),
        (CustomerAddressModel, "country_code", "br"),
    ],
)
def test_database_rejects_invalid_child_values(
    model: type[DeclarativeBase], field: str, value: object
) -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            customer = data.customer()
            await CustomerRepository(session, company_id=data.company_id).add(
                customer, actor_id=data.actor_id
            )
            row: CustomerContactModel | CustomerAddressModel
            if model is CustomerContactModel:
                row = CustomerContactModel(
                    id=uuid4(),
                    company_id=data.company_id,
                    customer_id=customer.id,
                    role=CustomerContactRole.BILLING,
                    kind=CustomerContactKind.EMAIL,
                    value="financeiro@cliente.com",
                    name=None,
                    is_primary=False,
                    created_by=data.actor_id,
                )
            else:
                row = CustomerAddressModel(
                    id=uuid4(),
                    company_id=data.company_id,
                    customer_id=customer.id,
                    role=CustomerAddressRole.BILLING,
                    line1="Rua Um",
                    city="Sao Paulo",
                    state="SP",
                    postal_code="01234567",
                    country_code="BR",
                    line2=None,
                    district=None,
                    is_primary=False,
                    created_by=data.actor_id,
                )
            setattr(row, field, value)
            session.add(row)
            with pytest.raises(IntegrityError):
                await session.flush()

    asyncio.run(scenario())
