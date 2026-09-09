"""M14 update application rules."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel
from erp.modules.customer.application.commands import CommandMetadata, CustomerCommandResult
from erp.modules.customer.application.permissions import CUSTOMER_UPDATE, CustomerAuthorization
from erp.modules.customer.application.updates import (
    CustomerUpdateService,
    CustomerUpdateStore,
    UpdateCustomer,
    apply_customer_update,
)
from erp.modules.customer.domain import Customer, CustomerStatus, CustomerType, TaxIdKind
from erp.platform.errors import ApplicationError


class FakeAuthorization:
    calls: list[tuple[object, object, bool]]

    def __init__(self) -> None:
        self.calls = []

    async def require(
        self,
        context: SecurityContext,
        company_id: object,
        permission: object,
        *,
        write: bool = False,
    ) -> None:
        self.calls.append((company_id, permission, write))


class FakeStore:
    command: UpdateCustomer | None = None

    async def update(self, command: UpdateCustomer, actor_id: object) -> CustomerCommandResult:
        self.command = command
        customer = _customer().update_master(legal_name="Changed", trade_name=None)
        return CustomerCommandResult(customer, None, None)


def _customer() -> Customer:
    return Customer.create(
        company_id=uuid4(),
        customer_type=CustomerType.INDIVIDUAL,
        identity_type=TaxIdKind.CPF,
        identity_value="52998224725",
        legal_name="Cliente",
        trade_name="Loja",
    )


def _command(
    customer: Customer,
    *,
    expected_version: int | None = None,
    legal_name: str | None = None,
    trade_name: str | None = None,
    clear_trade_name: bool = False,
    status: CustomerStatus | None = None,
) -> UpdateCustomer:
    return UpdateCustomer(
        company_id=customer.company_id,
        customer_id=customer.id,
        expected_version=customer.version if expected_version is None else expected_version,
        metadata=CommandMetadata(uuid4(), uuid4()),
        legal_name=legal_name,
        trade_name=trade_name,
        clear_trade_name=clear_trade_name,
        status=status,
    )


def _context(user_id: object) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(cast(UUID, user_id), uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=frozenset(),
        scopes=frozenset(),
    )


def test_apply_customer_update_changes_master_data_and_status() -> None:
    customer = _customer()
    changed = apply_customer_update(
        customer,
        _command(
            customer,
            legal_name="Novo cliente",
            clear_trade_name=True,
            status=CustomerStatus.BLOCKED,
        ),
    )

    assert changed.legal_name == "Novo cliente"
    assert changed.trade_name is None
    assert changed.status is CustomerStatus.BLOCKED
    assert changed.version == 3


def test_apply_customer_update_accepts_noop_but_rejects_empty_and_stale() -> None:
    customer = _customer()
    assert (
        apply_customer_update(customer, _command(customer, legal_name=customer.legal_name))
        is customer
    )
    with pytest.raises(ApplicationError) as empty:
        apply_customer_update(customer, _command(customer))
    assert empty.value.code == "EMPTY_PATCH"
    with pytest.raises(ApplicationError) as stale:
        apply_customer_update(customer, _command(customer, expected_version=99))
    assert stale.value.code == "VERSION_CONFLICT"


def test_apply_customer_update_translates_domain_errors() -> None:
    customer = _customer()
    blocked = customer.transition_status(CustomerStatus.BLOCKED)
    with pytest.raises(ApplicationError) as captured:
        apply_customer_update(
            blocked,
            _command(blocked, status=CustomerStatus.INACTIVE),
        )
    assert captured.value.code == "BUSINESS_VALIDATION_ERROR"


def test_update_service_authorizes_write_before_store() -> None:
    async def scenario() -> None:
        customer = _customer()
        authorization = FakeAuthorization()
        store = FakeStore()
        service = CustomerUpdateService(
            cast(CustomerUpdateStore, store), cast(CustomerAuthorization, authorization)
        )
        command = _command(customer, legal_name="Changed")
        await service.update(_context(customer.id), command)

        assert authorization.calls == [(customer.company_id, CUSTOMER_UPDATE, True)]
        assert store.command == command

    asyncio.run(scenario())
