"""Customer group commands and queries stay inside the M14 application boundary."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.customer.application.commands import CommandMetadata
from erp.modules.customer.application.permissions import (
    CUSTOMER_READ,
    CUSTOMER_UPDATE,
    CustomerAuthorization,
)
from erp.modules.customer.domain import CustomerGroup, CustomerGroupMember
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class CreateCustomerGroup:
    company_id: UUID
    code: str
    name: str
    description: str | None


@dataclass(frozen=True, slots=True)
class AssignCustomerGroup:
    company_id: UUID
    customer_id: UUID
    customer_group_id: UUID
    metadata: CommandMetadata


@dataclass(frozen=True, slots=True)
class CustomerGroupPage:
    items: tuple[CustomerGroup, ...]
    page: int
    page_size: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class CustomerGroupAssignmentResult:
    member: CustomerGroupMember
    event_id: UUID
    audit_event_id: UUID


class CustomerGroupStore(Protocol):
    async def list_groups(
        self, company_id: UUID, *, page: int, page_size: int, active: bool | None
    ) -> CustomerGroupPage: ...

    async def create_group(self, group: CustomerGroup, actor_id: UUID) -> CustomerGroup: ...

    async def assign(
        self, command: AssignCustomerGroup, actor_id: UUID
    ) -> CustomerGroupAssignmentResult: ...


class CustomerGroupService:
    def __init__(self, store: CustomerGroupStore, authorization: CustomerAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def list_groups(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        active: bool | None = None,
    ) -> CustomerGroupPage:
        await self._authorization.require(context, company_id, CUSTOMER_READ)
        if not 1 <= page <= 100_000 or not 1 <= page_size <= 100:
            raise ApplicationError(
                code="VALIDATION_ERROR", message="Invalid pagination.", status_code=422
            )
        return await self._store.list_groups(
            company_id, page=page, page_size=page_size, active=active
        )

    async def create_group(
        self, context: SecurityContext, command: CreateCustomerGroup
    ) -> CustomerGroup:
        await self._authorization.require(context, command.company_id, CUSTOMER_UPDATE, write=True)
        group = CustomerGroup.create(
            company_id=command.company_id,
            code=command.code,
            name=command.name,
            description=command.description,
        )
        return await self._store.create_group(group, context.principal.user_id)

    async def assign(
        self, context: SecurityContext, command: AssignCustomerGroup
    ) -> CustomerGroupAssignmentResult:
        await self._authorization.require(context, command.company_id, CUSTOMER_UPDATE, write=True)
        return await self._store.assign(command, context.principal.user_id)


__all__ = [
    "AssignCustomerGroup",
    "CreateCustomerGroup",
    "CustomerGroupAssignmentResult",
    "CustomerGroupPage",
    "CustomerGroupService",
    "CustomerGroupStore",
]
