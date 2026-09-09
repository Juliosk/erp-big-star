"""Tenant-bound repositories for M14 customer contacts and addresses."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.customer.domain import (
    CustomerAddress,
    CustomerAddressRole,
    CustomerContact,
    CustomerContactKind,
    CustomerContactRole,
)
from erp.modules.customer.infrastructure.contact_address_model import (
    CustomerAddressModel,
    CustomerContactModel,
)
from erp.modules.customer.infrastructure.customer_repository import CustomerRepository
from erp.platform.errors import ApplicationError


def _contact(model: CustomerContactModel) -> CustomerContact:
    return CustomerContact(
        id=model.id,
        company_id=model.company_id,
        customer_id=model.customer_id,
        role=CustomerContactRole(model.role),
        kind=CustomerContactKind(model.kind),
        value=model.value,
        name=model.name,
        is_primary=model.is_primary,
    )


def _address(model: CustomerAddressModel) -> CustomerAddress:
    return CustomerAddress(
        id=model.id,
        company_id=model.company_id,
        customer_id=model.customer_id,
        role=CustomerAddressRole(model.role),
        line1=model.line1,
        city=model.city,
        state=model.state,
        postal_code=model.postal_code,
        country_code=model.country_code,
        line2=model.line2,
        district=model.district,
        is_primary=model.is_primary,
    )


class CustomerContactAddressRepository:
    """One company-scoped child repository, never usable without a parent customer."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add_contact(self, contact: CustomerContact, *, actor_id: UUID) -> None:
        self._validate_contact(contact, actor_id)
        await self._require_customer(contact.customer_id)
        self._session.add(
            CustomerContactModel(
                id=contact.id,
                company_id=self._company_id,
                customer_id=contact.customer_id,
                role=contact.role,
                kind=contact.kind,
                value=contact.value,
                name=contact.name,
                is_primary=contact.is_primary,
                created_by=actor_id,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code="CUSTOMER_CONTACT_CONFLICT",
                    message="This customer contact already exists.",
                    status_code=409,
                ) from error
            raise

    async def add_address(self, address: CustomerAddress, *, actor_id: UUID) -> None:
        self._validate_address(address, actor_id)
        await self._require_customer(address.customer_id)
        self._session.add(
            CustomerAddressModel(
                id=address.id,
                company_id=self._company_id,
                customer_id=address.customer_id,
                role=address.role,
                line1=address.line1,
                city=address.city,
                state=address.state,
                postal_code=address.postal_code,
                country_code=address.country_code,
                line2=address.line2,
                district=address.district,
                is_primary=address.is_primary,
                created_by=actor_id,
            )
        )
        await self._session.flush()

    async def list_contacts(self, customer_id: UUID) -> tuple[CustomerContact, ...]:
        await self._require_customer(customer_id)
        result = await self._session.scalars(
            select(CustomerContactModel)
            .where(
                CustomerContactModel.company_id == self._company_id,
                CustomerContactModel.customer_id == customer_id,
            )
            .order_by(CustomerContactModel.role, CustomerContactModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_contact(model) for model in result)

    async def list_addresses(self, customer_id: UUID) -> tuple[CustomerAddress, ...]:
        await self._require_customer(customer_id)
        result = await self._session.scalars(
            select(CustomerAddressModel)
            .where(
                CustomerAddressModel.company_id == self._company_id,
                CustomerAddressModel.customer_id == customer_id,
            )
            .order_by(CustomerAddressModel.role, CustomerAddressModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_address(model) for model in result)

    async def _require_customer(self, customer_id: UUID) -> None:
        if (
            await CustomerRepository(self._session, company_id=self._company_id).get(customer_id)
            is None
        ):
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Customer not found.", status_code=404
            )

    def _validate_contact(self, contact: CustomerContact, actor_id: UUID) -> None:
        if contact.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The contact is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    def _validate_address(self, address: CustomerAddress, actor_id: UUID) -> None:
        if address.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The address is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")


__all__ = ["CustomerContactAddressRepository"]
