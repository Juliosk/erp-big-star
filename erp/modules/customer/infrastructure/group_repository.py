"""Tenant-bound persistence for M14 customer groups and group membership."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.customer.domain import CustomerGroup, CustomerGroupMember
from erp.modules.customer.infrastructure.customer_repository import CustomerRepository
from erp.modules.customer.infrastructure.group_model import (
    CustomerGroupMemberModel,
    CustomerGroupModel,
)
from erp.platform.errors import ApplicationError


def _group(model: CustomerGroupModel) -> CustomerGroup:
    return CustomerGroup(
        id=model.id,
        company_id=model.company_id,
        code=model.code,
        name=model.name,
        description=model.description,
        active=model.active,
        version=model.version,
    )


def _member(model: CustomerGroupMemberModel) -> CustomerGroupMember:
    return CustomerGroupMember(
        id=model.id,
        company_id=model.company_id,
        customer_id=model.customer_id,
        customer_group_id=model.customer_group_id,
    )


class CustomerGroupRepository:
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add_group(self, group: CustomerGroup, *, actor_id: UUID) -> None:
        self._validate_group(group, actor_id)
        self._session.add(
            CustomerGroupModel(
                id=group.id,
                company_id=self._company_id,
                code=group.code,
                name=group.name,
                description=group.description,
                active=group.active,
                created_by=actor_id,
                updated_by=actor_id,
                version=group.version,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code="CUSTOMER_GROUP_CONFLICT",
                    message="This customer group already exists.",
                    status_code=409,
                ) from error
            raise

    async def get_group(self, group_id: UUID) -> CustomerGroup | None:
        model = await self._session.get(
            CustomerGroupModel,
            group_id,
            populate_existing=True,
        )
        if model is None or model.company_id != self._company_id:
            return None
        return _group(model)

    async def list_groups(
        self, *, limit: int, offset: int, active: bool | None = None
    ) -> tuple[CustomerGroup, ...]:
        statement = (
            select(CustomerGroupModel)
            .where(CustomerGroupModel.company_id == self._company_id)
            .order_by(CustomerGroupModel.name, CustomerGroupModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        if active is not None:
            statement = statement.where(CustomerGroupModel.active == active)
        result = await self._session.scalars(statement)
        return tuple(_group(model) for model in result)

    async def assign_member(
        self, member: CustomerGroupMember, *, actor_id: UUID
    ) -> CustomerGroupMember:
        self._validate_member(member, actor_id)
        await self._require_group(member.customer_group_id)
        await self._require_customer(member.customer_id)
        self._session.add(
            CustomerGroupMemberModel(
                id=member.id,
                company_id=self._company_id,
                customer_id=member.customer_id,
                customer_group_id=member.customer_group_id,
                created_by=actor_id,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code="CUSTOMER_GROUP_MEMBER_CONFLICT",
                    message="This customer already belongs to the group.",
                    status_code=409,
                ) from error
            raise
        return member

    async def list_members(self, customer_id: UUID) -> tuple[CustomerGroupMember, ...]:
        await self._require_customer(customer_id)
        result = await self._session.scalars(
            select(CustomerGroupMemberModel)
            .where(
                CustomerGroupMemberModel.company_id == self._company_id,
                CustomerGroupMemberModel.customer_id == customer_id,
            )
            .order_by(CustomerGroupMemberModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_member(model) for model in result)

    async def _require_customer(self, customer_id: UUID) -> None:
        if (
            await CustomerRepository(self._session, company_id=self._company_id).get(customer_id)
            is None
        ):
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Customer not found.", status_code=404
            )

    async def _require_group(self, group_id: UUID) -> CustomerGroup:
        group = await self.get_group(group_id)
        if group is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Customer group not found.", status_code=404
            )
        if not group.active:
            raise ApplicationError(
                code="CUSTOMER_GROUP_INACTIVE",
                message="Inactive customer groups cannot receive new members.",
                status_code=409,
            )
        return group

    def _validate_group(self, group: CustomerGroup, actor_id: UUID) -> None:
        if group.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The customer group is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    def _validate_member(self, member: CustomerGroupMember, actor_id: UUID) -> None:
        if member.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The customer group membership is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")


__all__ = ["CustomerGroupRepository"]
