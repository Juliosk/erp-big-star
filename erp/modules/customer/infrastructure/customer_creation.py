"""Create + Idempotency + Audit + Outbox commit or roll back together."""

from uuid import UUID

from erp.modules.customer.application.commands import CreateCustomer, CustomerCommandResult
from erp.modules.customer.domain import Customer
from erp.modules.customer.infrastructure.customer_effects import CustomerEffects
from erp.modules.customer.infrastructure.customer_repository import CustomerRepository
from erp.platform.database import Database
from erp.platform.idempotency import IdempotencyService


class PostgresCustomerCreation:
    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def create(
        self, customer: Customer, command: CreateCustomer, actor_id: UUID
    ) -> CustomerCommandResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"customer:{customer.company_id}:{actor_id}",
                operation="customer.create",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                if decision.response_body is None:
                    raise RuntimeError("Stored customer replay has no response body.")
                return CustomerCommandResult.replay(decision.response_body)
            await CustomerRepository(session, company_id=customer.company_id).add(
                customer, actor_id=actor_id
            )
            result = await CustomerEffects().record(
                session,
                customer,
                actor_id=actor_id,
                metadata=command.metadata,
                event_type="CustomerCreated",
                payload={
                    "customer_id": str(customer.id),
                    "type": customer.customer_type,
                    "identity_ref": customer.identity_ref,
                },
            )
            await self._idempotency.complete(
                session, decision, response_status=201, response_body=result.to_dict()
            )
            return result


__all__ = ["PostgresCustomerCreation"]
