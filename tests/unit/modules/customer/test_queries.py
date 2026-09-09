"""M14 query service gates authorization and translates empty reads."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.application.permissions import CUSTOMER_READ, CustomerAuthorization
from erp.modules.customer.application.queries import (
    CustomerDirectory,
    CustomerPage,
    CustomerQueries,
)
from erp.modules.customer.domain import Customer, CustomerStatus, CustomerType, TaxIdKind
from erp.platform.errors import ApplicationError


class FakeAuthorization:
    calls: list[tuple[UUID, object, bool]]

    def __init__(self) -> None:
        self.calls = []

    async def require(
        self, context: SecurityContext, company_id: UUID, permission: object, *, write: bool = False
    ) -> None:
        self.calls.append((company_id, permission, write))


class FakeDirectory:
    customer: Customer | None
    list_calls: list[tuple[UUID, int, int, CustomerStatus | None, CustomerType | None]]

    def __init__(self, customer: Customer | None) -> None:
        self.customer = customer
        self.list_calls = []

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: CustomerStatus | None,
        customer_type: CustomerType | None,
    ) -> CustomerPage:
        self.list_calls.append((company_id, page, page_size, status, customer_type))
        return CustomerPage(
            (self.customer,) if self.customer is not None else (), page, page_size, False
        )

    async def get(self, company_id: UUID, customer_id: UUID) -> Customer | None:
        return (
            self.customer if self.customer is not None and self.customer.id == customer_id else None
        )


def _customer() -> Customer:
    return Customer.create(
        company_id=uuid4(),
        customer_type=CustomerType.INDIVIDUAL,
        identity_type=TaxIdKind.CPF,
        identity_value="52998224725",
        legal_name="Cliente",
    )


def test_list_authorizes_and_delegates_filters() -> None:
    async def scenario() -> None:
        customer = _customer()
        authorization = FakeAuthorization()
        directory = FakeDirectory(customer)
        service = CustomerQueries(
            cast(CustomerDirectory, directory), cast(CustomerAuthorization, authorization)
        )
        page = await service.list(
            cast(SecurityContext, object()),
            customer.company_id,
            page=2,
            page_size=10,
            status=CustomerStatus.ACTIVE,
            customer_type=CustomerType.INDIVIDUAL,
        )
        assert page.items == (customer,)
        assert authorization.calls == [(customer.company_id, CUSTOMER_READ, False)]
        assert directory.list_calls == [
            (
                customer.company_id,
                2,
                10,
                CustomerStatus.ACTIVE,
                CustomerType.INDIVIDUAL,
            )
        ]

    asyncio.run(scenario())


@pytest.mark.parametrize(("page", "page_size"), [(0, 10), (1, 0), (100_001, 10), (1, 101)])
def test_list_rejects_invalid_pagination_after_authorization(page: int, page_size: int) -> None:
    async def scenario() -> None:
        customer = _customer()
        authorization = FakeAuthorization()
        service = CustomerQueries(
            cast(CustomerDirectory, FakeDirectory(customer)),
            cast(CustomerAuthorization, authorization),
        )
        with pytest.raises(ApplicationError) as captured:
            await service.list(
                cast(SecurityContext, object()),
                customer.company_id,
                page=page,
                page_size=page_size,
            )
        assert captured.value.code == "VALIDATION_ERROR"
        assert authorization.calls == [(customer.company_id, CUSTOMER_READ, False)]

    asyncio.run(scenario())


def test_get_returns_customer_or_not_found() -> None:
    async def scenario() -> None:
        customer = _customer()
        service = CustomerQueries(
            cast(CustomerDirectory, FakeDirectory(customer)),
            cast(CustomerAuthorization, FakeAuthorization()),
        )
        assert (
            await service.get(cast(SecurityContext, object()), customer.company_id, customer.id)
            == customer
        )
        with pytest.raises(ApplicationError) as captured:
            await service.get(cast(SecurityContext, object()), customer.company_id, uuid4())
        assert captured.value.code == "RESOURCE_NOT_FOUND"

    asyncio.run(scenario())
