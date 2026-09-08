"""Technology-neutral product command inputs and replayable outcomes."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from erp.modules.product.domain import Product, ProductLifecycle, ProductType


@dataclass(frozen=True, slots=True)
class CommandMetadata:
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None = None


@dataclass(frozen=True, slots=True)
class CreateProduct:
    company_id: UUID
    code: str
    sku: str
    name: str
    product_type: ProductType
    uom: str
    idempotency_key: str
    metadata: CommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "code": self.code,
            "sku": self.sku,
            "name": self.name,
            "product_type": self.product_type,
            "uom": self.uom,
        }


def product_snapshot(product: Product) -> dict[str, object]:
    return {
        "id": str(product.id),
        "company_id": str(product.company_id),
        "code": product.code,
        "sku": product.sku,
        "name": product.name,
        "product_type": product.product_type,
        "uom": product.uom,
        "lifecycle": product.lifecycle,
        "version": product.version,
    }


@dataclass(frozen=True, slots=True)
class ProductCommandResult:
    product: Product
    event_id: UUID | None
    audit_event_id: UUID | None
    idempotency_replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "product": product_snapshot(self.product),
            "event_id": str(self.event_id) if self.event_id is not None else None,
            "audit_event_id": str(self.audit_event_id) if self.audit_event_id is not None else None,
            "idempotency_replayed": self.idempotency_replayed,
        }

    @classmethod
    def replay(cls, body: dict[str, Any]) -> ProductCommandResult:
        item = body["product"]
        return cls(
            product=Product(
                id=UUID(item["id"]),
                company_id=UUID(item["company_id"]),
                code=item["code"],
                sku=item["sku"],
                name=item["name"],
                product_type=ProductType(item["product_type"]),
                uom=item["uom"],
                lifecycle=ProductLifecycle(item["lifecycle"]),
                version=item["version"],
            ),
            event_id=UUID(body["event_id"]) if body["event_id"] is not None else None,
            audit_event_id=UUID(body["audit_event_id"])
            if body["audit_event_id"] is not None
            else None,
            idempotency_replayed=True,
        )


class ProductCreationStore(Protocol):
    async def create(
        self, product: Product, command: CreateProduct, actor_id: UUID
    ) -> ProductCommandResult: ...


__all__ = [
    "CommandMetadata",
    "CreateProduct",
    "ProductCommandResult",
    "ProductCreationStore",
    "product_snapshot",
]
