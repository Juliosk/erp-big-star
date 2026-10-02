"""Session-owning M6 supplier adapter."""

from uuid import UUID

from erp.modules.procurement.application.suppliers import (
    SupplierPage,
    UpdateSupplier,
    apply_supplier_update,
)
from erp.modules.procurement.domain import Supplier, SupplierStatus
from erp.modules.procurement.infrastructure.supplier_repository import SupplierRepository
from erp.platform.database import Database
from erp.platform.errors import ApplicationError


class PostgresSupplierStore:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(self, supplier: Supplier, *, actor_id: UUID) -> Supplier:
        async with self._database.session() as session, session.begin():
            repository = SupplierRepository(session, company_id=supplier.company_id)
            initial = Supplier(
                id=supplier.id,
                company_id=supplier.company_id,
                kind=supplier.kind,
                tax_identity=supplier.tax_identity,
                legal_name=supplier.legal_name,
                trade_name=supplier.trade_name,
                status=supplier.status,
                sites=(),
                version=1,
            )
            await repository.add(initial, actor_id=actor_id)
            if supplier == initial:
                return initial
            return await repository.save(supplier, actor_id=actor_id, expected_version=1)

    async def update(self, command: UpdateSupplier, *, actor_id: UUID) -> Supplier:
        async with self._database.session() as session, session.begin():
            repository = SupplierRepository(session, company_id=command.company_id)
            before = await repository.get(command.supplier_id)
            if before is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND", message="Supplier not found.", status_code=404
                )
            changed = apply_supplier_update(before, command)
            if changed == before:
                return before
            return await repository.save(
                changed, actor_id=actor_id, expected_version=command.expected_version
            )

    async def get(self, company_id: UUID, supplier_id: UUID) -> Supplier | None:
        async with self._database.session() as session:
            return await SupplierRepository(session, company_id=company_id).get(supplier_id)

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        status: SupplierStatus | None,
        document: str | None,
    ) -> SupplierPage:
        async with self._database.session() as session:
            repository = SupplierRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            items = await repository.list(
                limit=page_size,
                offset=offset,
                status=status,
                identity_value=document,
            )
            more = await repository.list(
                limit=1,
                offset=offset + page_size,
                status=status,
                identity_value=document,
            )
            return SupplierPage(items, page, page_size, bool(more))


__all__ = ["PostgresSupplierStore"]
