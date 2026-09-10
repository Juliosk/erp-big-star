"""Customer 360 application service stays read-only and tenant-gated."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.application.customer360 import (
    Customer360Directory,
    Customer360Service,
    Customer360Snapshot,
    CustomerMergeStatus,
)
from erp.modules.customer.application.permissions import CUSTOMER_READ, CustomerAuthorization
from erp.modules.customer.domain import Customer, CustomerType, TaxIdKind
from erp.platform.errors import ApplicationError


class FakeAuthorization:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, object, bool]] = []

    async def require(
        self, context: SecurityContext, company_id: UUID, permission: object, *, write: bool = False
    ) -> None:
        self.calls.append((company_id, permission, write))


class FakeDirectory:
    def __init__(self, snapshot: Customer360Snapshot | None) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[UUID, UUID]] = []

    async def get(self, company_id: UUID, customer_id: UUID) -> Customer360Snapshot | None:
        self.calls.append((company_id, customer_id))
        return self.snapshot


def _customer() -> Customer:
    return Customer.create(
        company_id=uuid4(),
        customer_type=CustomerType.INDIVIDUAL,
        identity_type=TaxIdKind.CPF,
        identity_value="52998224725",
        legal_name="Maria Souza",
    )


def _snapshot(customer: Customer) -> Customer360Snapshot:
    return Customer360Snapshot(
        customer=customer,
        contacts=(),
        addresses=(),
        groups=(),
        merge_status=CustomerMergeStatus(duplicate_candidates=(), pending_merge_requests=()),
    )


def test_customer_360_authorizes_and_returns_snapshot() -> None:
    async def scenario() -> None:
        customer = _customer()
        authorization = FakeAuthorization()
        directory = FakeDirectory(_snapshot(customer))
        service = Customer360Service(
            cast(Customer360Directory, directory),
            cast(CustomerAuthorization, authorization),
        )

        result = await service.get(
            cast(SecurityContext, object()), customer.company_id, customer.id
        )

        assert result.customer == customer
        assert authorization.calls == [(customer.company_id, CUSTOMER_READ, False)]
        assert directory.calls == [(customer.company_id, customer.id)]

    asyncio.run(scenario())


def test_customer_360_translates_missing_snapshot_to_not_found() -> None:
    async def scenario() -> None:
        company_id, customer_id = uuid4(), uuid4()
        service = Customer360Service(
            cast(Customer360Directory, FakeDirectory(None)),
            cast(CustomerAuthorization, FakeAuthorization()),
        )

        with pytest.raises(ApplicationError) as captured:
            await service.get(cast(SecurityContext, object()), company_id, customer_id)

        assert captured.value.code == "RESOURCE_NOT_FOUND"
        assert captured.value.status_code == 404

    asyncio.run(scenario())
