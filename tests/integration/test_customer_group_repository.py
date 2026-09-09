"""Direct M14 customer group repository edge cases."""

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from erp.modules.customer.domain import CustomerGroup, CustomerGroupMember
from erp.modules.customer.infrastructure.group_repository import CustomerGroupRepository
from erp.platform.errors import ApplicationError
from tests.integration.test_customer_persistence import customer_fixture

pytestmark = pytest.mark.integration


def test_group_repository_lists_members_and_negative_scope_edges() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="company UUID"):
            CustomerGroupRepository(cast(Any, object()), company_id=cast(Any, "bad"))
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            repository = CustomerGroupRepository(session, company_id=data.company_id)
            customer_repository = __import__(
                "erp.modules.customer.infrastructure.customer_repository",
                fromlist=["CustomerRepository"],
            ).CustomerRepository(session, company_id=data.company_id)
            customer = data.customer()
            await customer_repository.add(customer, actor_id=data.actor_id)
            group = CustomerGroup.create(
                company_id=data.company_id, code="VIP", name="Clientes VIP"
            )
            await repository.add_group(group, actor_id=data.actor_id)
            member = CustomerGroupMember.assign(
                company_id=data.company_id,
                customer_id=customer.id,
                customer_group_id=group.id,
            )
            assert await repository.get_group(uuid4()) is None
            assert await repository.list_groups(limit=10, offset=0, active=None) == (group,)
            assert await repository.assign_member(member, actor_id=data.actor_id) == member
            assert await repository.list_members(customer.id) == (member,)
            async with session.begin_nested() as savepoint:
                with pytest.raises(ApplicationError) as duplicate:
                    await repository.assign_member(
                        CustomerGroupMember.assign(
                            company_id=data.company_id,
                            customer_id=customer.id,
                            customer_group_id=group.id,
                        ),
                        actor_id=data.actor_id,
                    )
                assert duplicate.value.code == "CUSTOMER_GROUP_MEMBER_CONFLICT"
                await savepoint.rollback()
            with pytest.raises(ApplicationError) as missing_group:
                await repository.assign_member(
                    CustomerGroupMember.assign(
                        company_id=data.company_id,
                        customer_id=customer.id,
                        customer_group_id=uuid4(),
                    ),
                    actor_id=data.actor_id,
                )
            assert missing_group.value.code == "RESOURCE_NOT_FOUND"
            with pytest.raises(ApplicationError) as missing_customer:
                await repository.assign_member(
                    CustomerGroupMember.assign(
                        company_id=data.company_id,
                        customer_id=uuid4(),
                        customer_group_id=group.id,
                    ),
                    actor_id=data.actor_id,
                )
            assert missing_customer.value.code == "RESOURCE_NOT_FOUND"

    asyncio.run(scenario())


def test_group_repository_rejects_inactive_scope_and_actor_edges() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            repository = CustomerGroupRepository(session, company_id=data.company_id)
            customer_repository = __import__(
                "erp.modules.customer.infrastructure.customer_repository",
                fromlist=["CustomerRepository"],
            ).CustomerRepository(session, company_id=data.company_id)
            customer = data.customer()
            await customer_repository.add(customer, actor_id=data.actor_id)
            inactive = CustomerGroup.create(
                company_id=data.company_id,
                code="OLD",
                name="Grupo inativo",
                active=False,
            )
            await repository.add_group(inactive, actor_id=data.actor_id)
            with pytest.raises(ApplicationError) as inactive_group:
                await repository.assign_member(
                    CustomerGroupMember.assign(
                        company_id=data.company_id,
                        customer_id=customer.id,
                        customer_group_id=inactive.id,
                    ),
                    actor_id=data.actor_id,
                )
            assert inactive_group.value.code == "CUSTOMER_GROUP_INACTIVE"
            with pytest.raises(ApplicationError) as group_scope:
                await repository.add_group(
                    CustomerGroup.create(
                        company_id=data.other_company_id, code="FOREIGN", name="Outro"
                    ),
                    actor_id=data.actor_id,
                )
            assert group_scope.value.code == "SCOPE_FORBIDDEN"
            with pytest.raises(ApplicationError) as member_scope:
                await repository.assign_member(
                    CustomerGroupMember.assign(
                        company_id=data.other_company_id,
                        customer_id=customer.id,
                        customer_group_id=inactive.id,
                    ),
                    actor_id=data.actor_id,
                )
            assert member_scope.value.code == "SCOPE_FORBIDDEN"
            with pytest.raises(ValueError, match="actor UUID"):
                await repository.add_group(inactive, actor_id=cast(Any, "bad"))
            with pytest.raises(ValueError, match="actor UUID"):
                await repository.assign_member(
                    CustomerGroupMember.assign(
                        company_id=data.company_id,
                        customer_id=customer.id,
                        customer_group_id=inactive.id,
                    ),
                    actor_id=cast(Any, "bad"),
                )

    asyncio.run(scenario())


def test_group_repository_non_duplicate_integrity_errors_are_not_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReferentialIntegrityError(Exception):
        sqlstate = "23503"

    class SessionStub:
        def add(self, model: object) -> None:
            assert model is not None

        async def flush(self) -> None:
            raise IntegrityError(None, None, ReferentialIntegrityError())

    async def require_reference(reference_id: object) -> None:
        assert reference_id is not None

    company_id = uuid4()
    repository = CustomerGroupRepository(cast(Any, SessionStub()), company_id=company_id)
    group = CustomerGroup.create(company_id=company_id, code="VIP", name="VIP")
    with pytest.raises(IntegrityError):
        asyncio.run(repository.add_group(group, actor_id=uuid4()))
    monkeypatch.setattr(repository, "_require_group", require_reference)
    monkeypatch.setattr(repository, "_require_customer", require_reference)
    member = CustomerGroupMember.assign(
        company_id=company_id,
        customer_id=uuid4(),
        customer_group_id=uuid4(),
    )
    with pytest.raises(IntegrityError):
        asyncio.run(repository.assign_member(member, actor_id=uuid4()))
