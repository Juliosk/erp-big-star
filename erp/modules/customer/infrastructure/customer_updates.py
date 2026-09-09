"""Atomic optimistic customer mutations with their durable effects."""

from uuid import UUID

from erp.modules.customer.application.commands import CustomerCommandResult, customer_snapshot
from erp.modules.customer.application.updates import UpdateCustomer, apply_customer_update
from erp.modules.customer.infrastructure.customer_effects import CustomerEffects
from erp.modules.customer.infrastructure.customer_repository import CustomerRepository
from erp.platform.database import Database
from erp.platform.errors import ApplicationError


class PostgresCustomerUpdates:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def update(self, command: UpdateCustomer, actor_id: UUID) -> CustomerCommandResult:
        async with self._database.session() as session, session.begin():
            repository = CustomerRepository(session, company_id=command.company_id)
            before = await repository.get(command.customer_id)
            if before is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND", message="Customer not found.", status_code=404
                )
            changed = apply_customer_update(before, command)
            if changed == before:
                return CustomerCommandResult(before, None, None)
            saved = await repository.save(
                changed, actor_id=actor_id, expected_version=command.expected_version
            )
            old, new = customer_snapshot(before), customer_snapshot(saved)
            fields = sorted(
                key for key in ("legal_name", "trade_name", "status") if old[key] != new[key]
            )
            return await CustomerEffects().record(
                session,
                saved,
                actor_id=actor_id,
                metadata=command.metadata,
                event_type="CustomerUpdated",
                before=before,
                payload={
                    "customer_id": str(saved.id),
                    "changed_fields": fields,
                    "version": saved.version,
                },
            )


__all__ = ["PostgresCustomerUpdates"]
