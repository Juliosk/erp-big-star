"""Lifecycle, version, idempotency, audit and events in one PostgreSQL transaction."""

from datetime import UTC, datetime
from uuid import UUID

from erp.modules.product.application.commands import ProductCommandResult
from erp.modules.product.application.lifecycle import TransitionProduct
from erp.modules.product.domain import ProductLifecycle
from erp.modules.product.infrastructure.product_effects import ProductEffects
from erp.modules.product.infrastructure.product_repository import ProductRepository
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyService


class PostgresProductLifecycle:
    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def transition(self, command: TransitionProduct, actor_id: UUID) -> ProductCommandResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"product:{command.company_id}:{actor_id}",
                operation="product.lifecycle",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                if decision.response_body is None:
                    raise RuntimeError("Stored product replay has no response body.")
                return ProductCommandResult.replay(decision.response_body)
            repository = ProductRepository(session, company_id=command.company_id)
            before = await repository.get(command.product_id)
            if before is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND", message="Product not found.", status_code=404
                )
            if before.version != command.expected_version:
                raise OptimisticLockError(expected_version=command.expected_version)
            try:
                changed = before.transition(command.target)
            except ValueError as error:
                raise ApplicationError(
                    code="INVALID_LIFECYCLE_TRANSITION", message=str(error), status_code=409
                ) from error
            saved = await repository.save(changed, actor_id=actor_id)
            event_type = {
                ProductLifecycle.EM_HOMOLOGACAO: "ProductUpdated",
                ProductLifecycle.ATIVO: "ProductActivated",
                ProductLifecycle.FORA_DE_LINHA: "ProductDiscontinued",
            }[saved.lifecycle]
            payload: dict[str, object] = {"product_id": str(saved.id)}
            if saved.lifecycle is ProductLifecycle.EM_HOMOLOGACAO:
                payload.update(changed_fields=["lifecycle"], version=saved.version)
            else:
                payload["effective_at"] = datetime.now(UTC).isoformat()
                if saved.lifecycle is ProductLifecycle.ATIVO:
                    payload["sku"] = saved.sku
            result = await ProductEffects().record(
                session,
                saved,
                actor_id=actor_id,
                metadata=command.metadata,
                event_type=event_type,
                payload=payload,
                before=before,
            )
            await self._idempotency.complete(
                session, decision, response_status=200, response_body=result.to_dict()
            )
            return result


__all__ = ["PostgresProductLifecycle"]
