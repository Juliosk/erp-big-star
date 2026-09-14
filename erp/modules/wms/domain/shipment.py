"""Shipment lifecycle primitives owned by M10 WMS."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.wms.domain.picking import _normalize_code, _require_uuid


class ShipmentStatus(StrEnum):
    DRAFT = "DRAFT"
    READY_TO_DISPATCH = "READY_TO_DISPATCH"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class Shipment:
    id: UUID
    company_id: UUID
    shipment_code: str
    status: ShipmentStatus
    carrier_code: str | None
    tracking_code: str | None
    dispatched_at: datetime | None
    delivered_at: datetime | None
    version: int

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        shipment_code: str,
        carrier_code: str | None = None,
    ) -> Shipment:
        return cls(
            id=uuid4(),
            company_id=_require_uuid(company_id, "company_id"),
            shipment_code=_normalize_code(shipment_code, "shipment_code"),
            status=ShipmentStatus.DRAFT,
            carrier_code=None
            if carrier_code is None
            else _normalize_code(carrier_code, "carrier_code", max_length=32),
            tracking_code=None,
            dispatched_at=None,
            delivered_at=None,
            version=1,
        )

    def mark_ready(self) -> Shipment:
        if self.status is not ShipmentStatus.DRAFT:
            raise ValueError("Only draft shipments can be marked ready.")
        return self._replace(status=ShipmentStatus.READY_TO_DISPATCH, version=self.version + 1)

    def dispatch(
        self, *, tracking_code: str | None = None, now: datetime | None = None
    ) -> Shipment:
        if self.status is not ShipmentStatus.READY_TO_DISPATCH:
            raise ValueError("Only ready shipments can be dispatched.")
        return self._replace(
            status=ShipmentStatus.DISPATCHED,
            tracking_code=(
                self.tracking_code
                if tracking_code is None
                else _normalize_code(tracking_code, "tracking_code", max_length=80)
            ),
            dispatched_at=now or datetime.now(UTC),
            version=self.version + 1,
        )

    def _replace(
        self,
        *,
        status: ShipmentStatus,
        version: int,
        tracking_code: str | None = None,
        dispatched_at: datetime | None = None,
        delivered_at: datetime | None = None,
    ) -> Shipment:
        return Shipment(
            id=self.id,
            company_id=self.company_id,
            shipment_code=self.shipment_code,
            status=status,
            carrier_code=self.carrier_code,
            tracking_code=self.tracking_code if tracking_code is None else tracking_code,
            dispatched_at=self.dispatched_at if dispatched_at is None else dispatched_at,
            delivered_at=self.delivered_at if delivered_at is None else delivered_at,
            version=version,
        )


__all__ = ["Shipment", "ShipmentStatus"]

