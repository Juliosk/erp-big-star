"""Session-owning M4 Sales Order query adapter."""

from uuid import UUID

from erp.modules.sales.application.orders import SalesOrderPage, SalesOrderStore
from erp.modules.sales.domain import SalesOrder
from erp.modules.sales.infrastructure.order_repository import SalesOrderRepository
from erp.platform.database import Database


class PostgresSalesOrders(SalesOrderStore):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def list(
        self, company_id: UUID, *, page: int, page_size: int
    ) -> SalesOrderPage:
        offset = (page - 1) * page_size
        async with self._database.session() as session:
            repository = SalesOrderRepository(session, company_id=company_id)
            items = await repository.list(limit=page_size, offset=offset)
            more = await repository.list(limit=1, offset=offset + page_size)
        return SalesOrderPage(items, page, page_size, bool(more))

    async def get(self, company_id: UUID, order_id: UUID) -> SalesOrder | None:
        async with self._database.session() as session:
            return await SalesOrderRepository(session, company_id=company_id).get(order_id)


__all__ = ["PostgresSalesOrders"]
