"""Atomic optimistic product mutations with their durable effects."""

from uuid import UUID

from erp.modules.product.application.commands import ProductCommandResult, product_snapshot
from erp.modules.product.application.updates import UpdateProduct, apply_details
from erp.modules.product.infrastructure.product_effects import ProductEffects
from erp.modules.product.infrastructure.product_repository import ProductRepository
from erp.platform.database import Database
from erp.platform.errors import ApplicationError


class PostgresProductUpdates:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def update(self, command: UpdateProduct, actor_id: UUID) -> ProductCommandResult:
        async with self._database.session() as session, session.begin():
            repository = ProductRepository(session, company_id=command.company_id)
            before = await repository.get(command.product_id)
            if before is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND", message="Product not found.", status_code=404
                )
            changed = apply_details(before, command)
            if changed == before:
                return ProductCommandResult(before, None, None)
            saved = await repository.save(changed, actor_id=actor_id)
            old, new = product_snapshot(before), product_snapshot(saved)
            fields = sorted(key for key in ("name", "uom") if old[key] != new[key])
            return await ProductEffects().record(
                session,
                saved,
                actor_id=actor_id,
                metadata=command.metadata,
                event_type="ProductUpdated",
                before=before,
                payload={
                    "product_id": str(saved.id),
                    "changed_fields": fields,
                    "version": saved.version,
                },
            )


__all__ = ["PostgresProductUpdates"]
