"""Public contracts exposed by M10 WMS to other bounded contexts."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
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


@dataclass(frozen=True, slots=True)
class OutboundShipmentReference:
    company_id: UUID
    shipment_id: UUID
    status: str
    carrier_code: str
    tracking_code: str
    dispatched_at: datetime
    package_ids: tuple[UUID, ...]
    version: int

    def to_dict(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "shipment_id": str(self.shipment_id),
            "status": self.status,
            "carrier_code": self.carrier_code,
            "tracking_code": self.tracking_code,
            "dispatched_at": self.dispatched_at.isoformat(),
            "package_ids": [str(value) for value in self.package_ids],
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> OutboundShipmentReference:
        packages = value.get("package_ids")
        if not isinstance(packages, list):
            raise ValueError("Stored WMS shipment package snapshot is invalid.")
        return cls(
            company_id=UUID(str(value["company_id"])),
            shipment_id=UUID(str(value["shipment_id"])),
            status=str(value["status"]),
            carrier_code=str(value["carrier_code"]),
            tracking_code=str(value["tracking_code"]),
            dispatched_at=datetime.fromisoformat(str(value["dispatched_at"])),
            package_ids=tuple(UUID(str(item)) for item in packages),
            version=int(str(value["version"])),
        )


class OutboundShipmentGateway(Protocol):
    async def dispatch(
        self,
        *,
        company_id: UUID,
        shipment_id: UUID,
        expected_version: int,
        carrier_code: str,
        tracking_code: str,
        actor_id: UUID,
    ) -> OutboundShipmentReference: ...


__all__ = [
    "OutboundShipmentGateway",
    "OutboundShipmentReference",
    "PickingTaskDraft",
    "PickingWaveReference",
    "PickingWaveRequest",
    "WmsWaveService",
]
