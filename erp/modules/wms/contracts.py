"""Public contracts exposed by M10 WMS to other bounded contexts."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PickingWaveRequest:
    company_id: UUID
    source_type: str
    source_id: UUID | None
    warehouse_id: UUID | None


@dataclass(frozen=True, slots=True)
class PickingTaskDraft:
    product_id: UUID
    quantity: Decimal
    lot_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PickingWaveReference:
    id: UUID
    company_id: UUID
    code: str
    status: str
    version: int


class WmsWaveService(Protocol):
    async def create_wave(
        self, request: PickingWaveRequest, tasks: tuple[PickingTaskDraft, ...]
    ) -> PickingWaveReference: ...


__all__ = [
    "PickingTaskDraft",
    "PickingWaveReference",
    "PickingWaveRequest",
    "WmsWaveService",
]

