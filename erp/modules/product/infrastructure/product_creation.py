"""Create + Idempotency + Audit + Outbox commit or roll back together."""

from uuid import UUID

from erp.modules.product.application.commands import CreateProduct, ProductCommandResult
from erp.modules.product.domain import Product
from erp.modules.product.infrastructure.product_effects import ProductEffects
from erp.modules.product.infrastructure.product_repository import ProductRepository
from erp.platform.database import Database
from erp.platform.idempotency import IdempotencyService


class PostgresProductCreation:
    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def create(
        self, product: Product, command: CreateProduct, actor_id: UUID
    ) -> ProductCommandResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"product:{product.company_id}:{actor_id}",
                operation="product.create",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                if decision.response_body is None:
                    raise RuntimeError("Stored product replay has no response body.")
                return ProductCommandResult.replay(decision.response_body)
            await ProductRepository(session, company_id=product.company_id).add(
                product, actor_id=actor_id
            )
            result = await ProductEffects().record(
                session,
                product,
                actor_id=actor_id,
                metadata=command.metadata,
                event_type="ProductCreated",
                payload={
                    "product_id": str(product.id),
                    "sku": product.sku,
                    "product_type": product.product_type,
                },
            )
            await self._idempotency.complete(
                session, decision, response_status=201, response_body=result.to_dict()
            )
            return result


__all__ = ["PostgresProductCreation"]
