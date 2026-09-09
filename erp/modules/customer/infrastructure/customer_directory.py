"""Session-owning read adapter; all queries delegate to the tenant-bound repository."""

from uuid import UUID

from erp.modules.customer.application.queries import CustomerPage
from erp.modules.customer.domain import Customer, CustomerStatus, CustomerType
from erp.modules.customer.infrastructure.customer_repository import CustomerRepository
from erp.platform.database import Database


class PostgresCustomerDirectory:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: CustomerStatus | None,
        customer_type: CustomerType | None,
    ) -> CustomerPage:
        async with self._database.session() as session:
            repository = CustomerRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list(
                limit=page_size,
                offset=offset,
                status=status,
                customer_type=customer_type,
            )
            more = await repository.list(
                limit=1,
                offset=offset + page_size,
                status=status,
                customer_type=customer_type,
            )
            return CustomerPage(items, page, page_size, bool(more))

    async def get(self, company_id: UUID, customer_id: UUID) -> Customer | None:
        async with self._database.session() as session:
            return await CustomerRepository(session, company_id=company_id).get(customer_id)


__all__ = ["PostgresCustomerDirectory"]
