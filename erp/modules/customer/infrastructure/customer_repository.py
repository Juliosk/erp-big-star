"""Tenant-bound M14 persistence; transactions and authorization belong to the caller."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.customer.domain import (
    Customer,
    CustomerStatus,
    CustomerTaxId,
    CustomerType,
    TaxIdKind,
)
from erp.modules.customer.infrastructure.customer_model import CustomerModel
from erp.platform.errors import ApplicationError


def _customer(model: CustomerModel) -> Customer:
    return Customer(
        id=model.id,
        company_id=model.company_id,
        customer_type=CustomerType(model.customer_type),
        tax_id=CustomerTaxId(TaxIdKind(model.identity_type), model.identity_value),
        legal_name=model.legal_name,
        trade_name=model.trade_name,
        status=CustomerStatus(model.status),
        version=model.version,
    )


class CustomerRepository:
    """One previously authorized company per instance, with no unscoped operations."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, customer: Customer, *, actor_id: UUID) -> None:
        """Flush a new active customer; never commit or publish an event."""
        self._validate_write(customer, actor_id)
        if customer.version != 1 or customer.status is not CustomerStatus.ACTIVE:
            raise ValueError("A new customer must start active at version one.")
        self._session.add(
            CustomerModel(
                id=customer.id,
                company_id=self._company_id,
                customer_type=customer.customer_type,
                identity_type=customer.tax_id.kind,
                identity_value=customer.tax_id.value,
                legal_name=customer.legal_name,
                trade_name=customer.trade_name,
                status=customer.status,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code="CUSTOMER_DUPLICATE_EXACT_MATCH",
                    message="A customer with this CPF/CNPJ already exists for the selected company.",
                    status_code=409,
                ) from error
            raise

    async def get(self, customer_id: UUID) -> Customer | None:
        """Return no data for missing customers or another company's customer."""
        result = await self._session.scalars(
            select(CustomerModel)
            .where(
                CustomerModel.company_id == self._company_id,
                CustomerModel.id == customer_id,
            )
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _customer(model)

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: CustomerStatus | None = None,
        customer_type: CustomerType | None = None,
    ) -> tuple[Customer, ...]:
        """Bounded, deterministic company directory; no cross-company consolidation."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100.")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer.")
        if status is not None and not isinstance(status, CustomerStatus):
            raise ValueError("status must be an official M14 status.")
        if customer_type is not None and not isinstance(customer_type, CustomerType):
            raise ValueError("customer_type must be an official M14 type.")
        statement = select(CustomerModel).where(CustomerModel.company_id == self._company_id)
        if status is not None:
            statement = statement.where(CustomerModel.status == status)
        if customer_type is not None:
            statement = statement.where(CustomerModel.customer_type == customer_type)
        result = await self._session.scalars(
            statement.order_by(CustomerModel.legal_name, CustomerModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_customer(model) for model in result)

    def _validate_write(self, customer: Customer, actor_id: UUID) -> None:
        if customer.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The customer is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")


__all__ = ["CustomerRepository", "_customer"]
