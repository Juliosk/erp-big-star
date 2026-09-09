"""Session-owning adapter for M14 customer groups."""

from uuid import UUID

from erp.modules.customer.application.groups import (
    AssignCustomerGroup,
    CustomerGroupAssignmentResult,
    CustomerGroupPage,
)
from erp.modules.customer.domain import CustomerGroup, CustomerGroupMember
from erp.modules.customer.infrastructure.group_effects import CustomerGroupEffects
from erp.modules.customer.infrastructure.group_repository import CustomerGroupRepository
from erp.platform.database import Database


class PostgresCustomerGroups:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_groups(
        self, company_id: UUID, *, page: int, page_size: int, active: bool | None
    ) -> CustomerGroupPage:
        async with self._database.session() as session:
            repository = CustomerGroupRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list_groups(limit=page_size, offset=offset, active=active)
            more = await repository.list_groups(limit=1, offset=offset + page_size, active=active)
            return CustomerGroupPage(items, page, page_size, bool(more))

    async def create_group(self, group: CustomerGroup, actor_id: UUID) -> CustomerGroup:
        async with self._database.session() as session, session.begin():
            await CustomerGroupRepository(session, company_id=group.company_id).add_group(
                group, actor_id=actor_id
            )
            return group

    async def assign(
        self, command: AssignCustomerGroup, actor_id: UUID
    ) -> CustomerGroupAssignmentResult:
        async with self._database.session() as session, session.begin():
            repository = CustomerGroupRepository(session, company_id=command.company_id)
            member = await repository.assign_member(
                CustomerGroupMember.assign(
                    company_id=command.company_id,
                    customer_id=command.customer_id,
                    customer_group_id=command.customer_group_id,
                ),
                actor_id=actor_id,
            )
            return await CustomerGroupEffects().record_assignment(
                session, member, actor_id=actor_id, metadata=command.metadata
            )


__all__ = ["PostgresCustomerGroups"]
