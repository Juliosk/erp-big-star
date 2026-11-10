"""Application ports and orchestration for multichannel sales fulfillment."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.application.lifecycle import CommandMetadata
from erp.modules.sales.application.permissions import (
    SALES_ORDERS_WRITE,
    SalesAuthorization,
)
from erp.modules.sales.domain import (
    ChannelOrderStatus,
    Marketplace,
    SalesShipment,
    SalesShipmentStatus,
    ShippingLabel,
)
from erp.modules.wms.contracts import OutboundShipmentReference
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class FulfillSalesOrder:
    company_id: UUID
    order_id: UUID
    wms_shipment_id: UUID
    carrier_service: str
    expected_order_version: int
    expected_wms_version: int
    idempotency_key: str
    metadata: CommandMetadata

    def __post_init__(self) -> None:
        for identity in (self.company_id, self.order_id, self.wms_shipment_id):
            if not isinstance(identity, UUID) or identity.int == 0:
                raise ValueError("Fulfillment identities must be non-zero UUIDs.")
        if (
            not isinstance(self.carrier_service, str)
            or not 1 <= len(self.carrier_service) <= 32
            or self.carrier_service != self.carrier_service.strip()
        ):
            raise ValueError("carrier_service must contain trimmed text.")
        for version in (self.expected_order_version, self.expected_wms_version):
            if type(version) is not int or version < 1:
                raise ValueError("Fulfillment versions must be positive integers.")
        if (
            not isinstance(self.idempotency_key, str)
            or not 1 <= len(self.idempotency_key) <= 128
            or self.idempotency_key != self.idempotency_key.strip()
        ):
            raise ValueError("idempotency_key must contain trimmed text.")

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "order_id": str(self.order_id),
            "wms_shipment_id": str(self.wms_shipment_id),
            "carrier_service": self.carrier_service,
            "expected_order_version": self.expected_order_version,
            "expected_wms_version": self.expected_wms_version,
        }


@dataclass(frozen=True, slots=True)
class SalesFulfillmentCandidate:
    company_id: UUID
    order_id: UUID
    channel_config_id: UUID
    account_id: UUID
    marketplace: Marketplace
    external_order_id: str
    order_status: ChannelOrderStatus
    order_version: int
    credential_reference: str


@dataclass(frozen=True, slots=True)
class ShippingLabelRequest:
    company_id: UUID
    order_id: UUID
    account_id: UUID
    marketplace: Marketplace
    external_order_id: str
    credential_reference: str
    carrier_service: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class SalesFulfillmentResult:
    shipment: SalesShipment
    order_status: ChannelOrderStatus
    order_version: int
    wms_shipment: OutboundShipmentReference
    event_id: UUID | None
    audit_event_id: UUID | None
    replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "shipment": sales_shipment_snapshot(self.shipment),
            "order_status": self.order_status,
            "order_version": self.order_version,
            "wms_shipment": self.wms_shipment.to_dict(),
            "event_id": str(self.event_id) if self.event_id is not None else None,
            "audit_event_id": (
                str(self.audit_event_id)
                if self.audit_event_id is not None
                else None
            ),
        }

    @classmethod
    def replay(cls, body: dict[str, Any]) -> SalesFulfillmentResult:
        shipment = body.get("shipment")
        wms_shipment = body.get("wms_shipment")
        if not isinstance(shipment, dict) or not isinstance(wms_shipment, dict):
            raise ValueError("Stored fulfillment replay has invalid snapshots.")
        return cls(
            shipment=sales_shipment_from_snapshot(shipment),
            order_status=ChannelOrderStatus(str(body["order_status"])),
            order_version=int(str(body["order_version"])),
            wms_shipment=OutboundShipmentReference.from_dict(wms_shipment),
            event_id=UUID(str(body["event_id"])) if body.get("event_id") else None,
            audit_event_id=(
                UUID(str(body["audit_event_id"]))
                if body.get("audit_event_id")
                else None
            ),
            replayed=True,
        )


class ShippingLabelGateway(Protocol):
    async def create_label(self, request: ShippingLabelRequest) -> ShippingLabel: ...


class SalesFulfillmentStore(Protocol):
    async def get_candidate(
        self, company_id: UUID, order_id: UUID
    ) -> SalesFulfillmentCandidate | None: ...

    async def fulfill(
        self,
        command: FulfillSalesOrder,
        label: ShippingLabel,
        actor_id: UUID,
    ) -> SalesFulfillmentResult: ...


class SalesFulfillmentService:
    def __init__(
        self,
        store: SalesFulfillmentStore,
        authorization: SalesAuthorization,
        shipping_gateways: dict[Marketplace, ShippingLabelGateway],
    ) -> None:
        self._store = store
        self._authorization = authorization
        self._shipping_gateways = dict(shipping_gateways)

    async def fulfill(
        self, context: SecurityContext, command: FulfillSalesOrder
    ) -> SalesFulfillmentResult:
        await self._authorization.require(
            context, command.company_id, SALES_ORDERS_WRITE, write=True
        )
        candidate = await self._store.get_candidate(
            command.company_id, command.order_id
        )
        if candidate is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Multichannel sales order not found.",
                status_code=404,
            )
        if candidate.order_status not in {
            ChannelOrderStatus.PAID,
            ChannelOrderStatus.SHIPPED,
        }:
            raise _fulfillment_conflict("Only paid orders can be fulfilled.")
        gateway = self._shipping_gateways.get(candidate.marketplace)
        if gateway is None:
            raise _fulfillment_conflict("Shipping gateway is not configured.")
        label = await gateway.create_label(
            ShippingLabelRequest(
                company_id=command.company_id,
                order_id=command.order_id,
                account_id=candidate.account_id,
                marketplace=candidate.marketplace,
                external_order_id=candidate.external_order_id,
                credential_reference=candidate.credential_reference,
                carrier_service=command.carrier_service,
                idempotency_key=(
                    f"sales-fulfillment:{command.company_id}:{command.order_id}"
                ),
            )
        )
        return await self._store.fulfill(
            command, label, context.principal.user_id
        )


def sales_shipment_snapshot(value: SalesShipment) -> dict[str, object]:
    return {
        "id": str(value.id),
        "company_id": str(value.company_id),
        "sales_order_id": str(value.sales_order_id),
        "wms_shipment_id": str(value.wms_shipment_id),
        "channel_config_id": str(value.channel_config_id),
        "account_id": str(value.account_id),
        "marketplace": value.marketplace,
        "external_order_id": value.external_order_id,
        "status": value.status,
        "carrier_code": value.label.carrier_code,
        "service_code": value.label.service_code,
        "tracking_code": value.label.tracking_code,
        "label_reference": value.label.label_reference,
        "dispatched_at": (
            value.dispatched_at.isoformat()
            if value.dispatched_at is not None
            else None
        ),
        "version": value.version,
    }


def sales_shipment_from_snapshot(value: dict[str, Any]) -> SalesShipment:
    return SalesShipment(
        id=UUID(str(value["id"])),
        company_id=UUID(str(value["company_id"])),
        sales_order_id=UUID(str(value["sales_order_id"])),
        wms_shipment_id=UUID(str(value["wms_shipment_id"])),
        channel_config_id=UUID(str(value["channel_config_id"])),
        account_id=UUID(str(value["account_id"])),
        marketplace=Marketplace(str(value["marketplace"])),
        external_order_id=str(value["external_order_id"]),
        status=SalesShipmentStatus(str(value["status"])),
        label=ShippingLabel(
            carrier_code=str(value["carrier_code"]),
            service_code=str(value["service_code"]),
            tracking_code=str(value["tracking_code"]),
            label_reference=str(value["label_reference"]),
        ),
        dispatched_at=(
            datetime.fromisoformat(str(value["dispatched_at"]))
            if value["dispatched_at"] is not None
            else None
        ),
        version=int(str(value["version"])),
    )


def _fulfillment_conflict(message: str) -> ApplicationError:
    return ApplicationError(
        code="SALES_FULFILLMENT_CONFLICT",
        message="Sales order fulfillment could not be completed.",
        status_code=409,
        details=[ErrorDetail(message=message)],
    )


__all__ = [
    "FulfillSalesOrder",
    "SalesFulfillmentCandidate",
    "SalesFulfillmentResult",
    "SalesFulfillmentService",
    "SalesFulfillmentStore",
    "ShippingLabelGateway",
    "ShippingLabelRequest",
    "sales_shipment_from_snapshot",
    "sales_shipment_snapshot",
]
