"""Explicit lifecycle commands; authorization is evaluated before persistence/replay."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.product.application.commands import CommandMetadata, ProductCommandResult
from erp.modules.product.application.permissions import (
    PRODUCT_ACTIVATE,
    PRODUCT_DISCONTINUE,
    ProductAuthorization,
)
from erp.modules.product.domain import ProductLifecycle


@dataclass(frozen=True, slots=True)
class TransitionProduct:
    company_id: UUID
    product_id: UUID
    target: ProductLifecycle
    expected_version: int
    idempotency_key: str
    metadata: CommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "product_id": str(self.product_id),
            "target": self.target,
            "expected_version": self.expected_version,
        }


class LifecycleStore(Protocol):
    async def transition(
        self, command: TransitionProduct, actor_id: UUID
    ) -> ProductCommandResult: ...


class ProductLifecycleService:
    def __init__(self, store: LifecycleStore, authorization: ProductAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def transition(
        self, context: SecurityContext, command: TransitionProduct
    ) -> ProductCommandResult:
        permission = (
            PRODUCT_DISCONTINUE
            if command.target is ProductLifecycle.FORA_DE_LINHA
            else PRODUCT_ACTIVATE
        )
        await self._authorization.require(context, command.company_id, permission, write=True)
        return await self._store.transition(command, context.principal.user_id)


__all__ = ["LifecycleStore", "ProductLifecycleService", "TransitionProduct"]
