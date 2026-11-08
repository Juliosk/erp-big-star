"""Framework-neutral production domain event contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from erp.modules.production.domain import InvalidProductionValueError


class ProductionEventType(StrEnum):
    ORDER_RELEASED = "ProductionOrderReleased"
    ORDER_COMPLETED = "ProductionOrderCompleted"
    OPERATION_COMPLETED = "OperationCompleted"
    MATERIAL_CONSUMED = "MaterialConsumed"
    SCRAP_RECORDED = "ScrapRecorded"


@dataclass(frozen=True, slots=True)
class ProductionDomainEvent:
    """Immutable production fact staged inside the caller transaction."""

    event_type: ProductionEventType
    company_id: UUID
    production_order_id: UUID
    aggregate_version: int
    occurred_at: datetime
    request_id: UUID
    correlation_id: UUID
    causation_id: UUID | None
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        for value, name in (
            (self.company_id, "company_id"),
            (self.production_order_id, "production_order_id"),
            (self.request_id, "request_id"),
            (self.correlation_id, "correlation_id"),
        ):
            if not isinstance(value, UUID) or value.int == 0:
                raise InvalidProductionValueError(f"{name} must be a non-zero UUID.")
        if self.causation_id is not None and self.causation_id.int == 0:
            raise InvalidProductionValueError("causation_id must be a non-zero UUID.")
        if type(self.aggregate_version) is not int or self.aggregate_version < 1:
            raise InvalidProductionValueError("aggregate_version must be positive.")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise InvalidProductionValueError("occurred_at must be timezone-aware.")
        if not isinstance(self.payload, dict):
            raise InvalidProductionValueError("payload must be a dictionary.")


class ProductionEventPublisher(Protocol):
    async def publish(self, event: ProductionDomainEvent) -> UUID: ...


__all__ = [
    "ProductionDomainEvent",
    "ProductionEventPublisher",
    "ProductionEventType",
]
