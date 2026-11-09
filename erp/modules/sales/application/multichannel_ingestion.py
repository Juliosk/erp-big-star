"""M3/M4 orchestration ports for deterministic multichannel order ingestion."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.contracts import InventoryReservationReference
from erp.modules.sales.application.lifecycle import CommandMetadata
from erp.modules.sales.application.permissions import SALES_CHANNELS_INGEST, SalesAuthorization
from erp.modules.sales.contracts import (
    ChannelFee,
    ChannelOrderReference,
    ChannelOrderStatus,
    ExternalChannelOrder,
    Marketplace,
    SalesChannelAccount,
)
from erp.modules.sales.domain import MultichannelSalesOrder
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class IngestMultichannelOrder:
    company_id: UUID
    channel_config_id: UUID
    marketplace: Marketplace
    external_order_id: str
    warehouse_id: UUID
    idempotency_key: str
    metadata: CommandMetadata
    payload: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        for identity in (self.company_id, self.channel_config_id, self.warehouse_id):
            if not isinstance(identity, UUID) or identity.int == 0:
                raise ValueError("Multichannel identities must be non-zero UUIDs.")
        if not isinstance(self.marketplace, Marketplace):
            raise ValueError("An official marketplace is required.")
        if (
            not isinstance(self.external_order_id, str)
            or not 1 <= len(self.external_order_id) <= 128
            or self.external_order_id != self.external_order_id.strip()
        ):
            raise ValueError("external_order_id must contain trimmed text.")
        if (
            not isinstance(self.idempotency_key, str)
            or not 1 <= len(self.idempotency_key) <= 128
            or self.idempotency_key != self.idempotency_key.strip()
        ):
            raise ValueError("idempotency_key must contain trimmed text.")
        if self.payload is not None:
            object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class MultichannelOrderIngestionResult:
    order: MultichannelSalesOrder
    reservation: InventoryReservationReference
    fees: tuple[ChannelFee, ...]
    event_id: UUID | None
    inventory_event_id: UUID | None
    audit_event_id: UUID | None
    inventory_audit_event_id: UUID | None
    replayed: bool = False


class MarketplaceOrderGateway(Protocol):
    """M3 adapter surface; tokens and transport remain outside Sales."""

    async def normalize_webhook(
        self,
        reference: ChannelOrderReference,
        payload: Mapping[str, object],
    ) -> ExternalChannelOrder: ...

    async def fetch_order(
        self,
        reference: ChannelOrderReference,
        credential_reference: str,
    ) -> ExternalChannelOrder: ...


class MultichannelOrderIngestionStore(Protocol):
    """Caller-owned transaction boundary implemented by the PostgreSQL adapter."""

    async def get_channel_account(
        self, company_id: UUID, channel_config_id: UUID
    ) -> SalesChannelAccount | None: ...

    async def ingest(
        self,
        command: IngestMultichannelOrder,
        normalized: ExternalChannelOrder,
        actor_id: UUID,
    ) -> MultichannelOrderIngestionResult: ...


class MultichannelOrderIngestionService:
    """Authorize, normalize and atomically persist/reserve one external order."""

    def __init__(
        self,
        store: MultichannelOrderIngestionStore,
        authorization: SalesAuthorization,
        gateways: Mapping[Marketplace, MarketplaceOrderGateway],
    ) -> None:
        self._store = store
        self._authorization = authorization
        self._gateways = dict(gateways)

    async def ingest(
        self,
        context: SecurityContext,
        command: IngestMultichannelOrder,
    ) -> MultichannelOrderIngestionResult:
        await self._authorization.require(
            context, command.company_id, SALES_CHANNELS_INGEST, write=True
        )
        account = await self._store.get_channel_account(
            command.company_id, command.channel_config_id
        )
        if account is None or not account.active:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Active sales channel account not found.",
                status_code=404,
            )
        if account.marketplace is not command.marketplace:
            raise _channel_error("Channel account does not match the requested marketplace.")
        gateway = self._gateways.get(command.marketplace)
        if gateway is None:
            raise _channel_error("Marketplace gateway is not configured.")
        reference = ChannelOrderReference(
            company_id=command.company_id,
            account_id=account.account_id,
            marketplace=command.marketplace,
            external_order_id=command.external_order_id,
        )
        if command.payload is None:
            normalized = await gateway.fetch_order(reference, account.credential_reference)
        else:
            normalized = await gateway.normalize_webhook(reference, command.payload)
        if normalized.reference != reference:
            raise _channel_error("Marketplace response crossed the requested order scope.")
        if normalized.status is not ChannelOrderStatus.PAID:
            raise _channel_error(
                "Only paid marketplace orders can enter the inventory reservation workflow."
            )
        return await self._store.ingest(command, normalized, context.principal.user_id)


def _channel_error(message: str) -> ApplicationError:
    return ApplicationError(
        code="INVALID_CHANNEL_ORDER",
        message="External channel order is invalid.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = [
    "IngestMultichannelOrder",
    "MarketplaceOrderGateway",
    "MultichannelOrderIngestionResult",
    "MultichannelOrderIngestionService",
    "MultichannelOrderIngestionStore",
]
