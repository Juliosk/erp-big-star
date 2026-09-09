"""Pure M14 customer group rules and application service wiring."""

import asyncio
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel
from erp.modules.customer.application.commands import CommandMetadata
from erp.modules.customer.application.groups import (
    AssignCustomerGroup,
    CreateCustomerGroup,
    CustomerGroupAssignmentResult,
    CustomerGroupPage,
    CustomerGroupService,
    CustomerGroupStore,
)
from erp.modules.customer.application.permissions import (
    CUSTOMER_READ,
    CUSTOMER_UPDATE,
    CustomerAuthorization,
)
from erp.modules.customer.domain import CustomerGroup, CustomerGroupMember
from erp.platform.errors import ApplicationError


class FakeAuthorization:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, object, bool]] = []

    async def require(
        self, context: SecurityContext, company_id: UUID, permission: object, *, write: bool = False
    ) -> None:
        self.calls.append((company_id, permission, write))


class FakeStore:
    def __init__(self) -> None:
        self.created: CustomerGroup | None = None
        self.assigned: AssignCustomerGroup | None = None

    async def list_groups(
        self, company_id: UUID, *, page: int, page_size: int, active: bool | None
    ) -> CustomerGroupPage:
        return CustomerGroupPage((), page, page_size, False)

    async def create_group(self, group: CustomerGroup, actor_id: UUID) -> CustomerGroup:
        self.created = group
        return group

    async def assign(
        self, command: AssignCustomerGroup, actor_id: UUID
    ) -> CustomerGroupAssignmentResult:
        self.assigned = command
        member = CustomerGroupMember.assign(
            company_id=command.company_id,
            customer_id=command.customer_id,
            customer_group_id=command.customer_group_id,
        )
        return CustomerGroupAssignmentResult(member, uuid4(), uuid4())


def _context(user_id: UUID) -> SecurityContext:
    return SecurityContext(
        principal=AuthenticatedPrincipal(user_id, uuid4(), AuthenticationLevel.LEVEL_1),
        permissions=frozenset(),
        scopes=frozenset(),
    )


def test_customer_group_normalizes_and_validates_identity() -> None:
    company_id = uuid4()
    group = CustomerGroup.create(
        company_id=company_id,
        code=" vip-01 ",
        name=" Clientes VIP ",
        description=" Segmentacao comercial ",
    )

    assert group.company_id == company_id
    assert group.code == "VIP-01"
    assert group.name == "Clientes VIP"
    assert group.description == "Segmentacao comercial"
    assert group.active is True
    assert group.version == 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"company_id": "bad"}, "UUID"),
        ({"code": "x"}, "code"),
        ({"code": "vip"}, "code"),
        ({"name": " "}, "name"),
        ({"description": " "}, "description"),
        ({"active": 1}, "boolean"),
        ({"version": 0}, "version"),
    ],
)
def test_customer_group_rejects_invalid_snapshots(changes: dict[str, object], message: str) -> None:
    from dataclasses import replace

    group = CustomerGroup.create(company_id=uuid4(), code="VIP", name="Clientes VIP")
    with pytest.raises(ValueError, match=message):
        cast(Any, replace)(group, **changes)


def test_customer_group_member_requires_scope_customer_and_group_ids() -> None:
    member = CustomerGroupMember.assign(
        company_id=uuid4(), customer_id=uuid4(), customer_group_id=uuid4()
    )
    assert isinstance(member.id, UUID)
    with pytest.raises(ValueError, match="UUID"):
        CustomerGroupMember(
            id=uuid4(),
            company_id=uuid4(),
            customer_id=uuid4(),
            customer_group_id=cast(UUID, "bad"),
        )


def test_group_service_authorizes_reads_writes_and_validates_pagination() -> None:
    async def scenario() -> None:
        company_id, actor_id = uuid4(), uuid4()
        authorization = FakeAuthorization()
        store = FakeStore()
        service = CustomerGroupService(
            cast(CustomerGroupStore, store), cast(CustomerAuthorization, authorization)
        )
        context = _context(actor_id)

        await service.list_groups(context, company_id, page=1, page_size=50)
        created = await service.create_group(
            context,
            CreateCustomerGroup(
                company_id=company_id, code="vip", name="Clientes VIP", description=None
            ),
        )
        command = AssignCustomerGroup(
            company_id, uuid4(), created.id, metadata=CommandMetadata(uuid4(), uuid4())
        )
        await service.assign(context, command)

        assert authorization.calls == [
            (company_id, CUSTOMER_READ, False),
            (company_id, CUSTOMER_UPDATE, True),
            (company_id, CUSTOMER_UPDATE, True),
        ]
        assert store.created == created
        assert store.assigned == command
        with pytest.raises(ApplicationError) as captured:
            await service.list_groups(context, company_id, page=0, page_size=50)
        assert captured.value.code == "VALIDATION_ERROR"

    asyncio.run(scenario())
