"""Public immutable canonical order contracts shared with channel adapters."""

from dataclasses import dataclass
from uuid import UUID

from erp.modules.sales.domain.channels import (
    ChannelFee,
    ChannelOrderItem,
    ChannelOrderReference,
    ChannelOrderSnapshot,
    ChannelOrderStatus,
    ChannelSkuMapping,
    ExternalChannelOrder,
    ExternalChannelOrderItem,
    Marketplace,
    SalesChannelAccount,
)


@dataclass(frozen=True, slots=True)
class ChannelFulfillmentUpdate:
    company_id: UUID
    account_id: UUID
    marketplace: Marketplace
    external_order_id: str
    status: ChannelOrderStatus
    tracking_code: str
    carrier_code: str

    def __post_init__(self) -> None:
        ChannelOrderReference(
            self.company_id,
            self.account_id,
            self.marketplace,
            self.external_order_id,
        )
        if self.status is not ChannelOrderStatus.SHIPPED:
            raise ValueError("Fulfillment synchronization requires SHIPPED status.")
        for name, value, maximum in (
            ("tracking_code", self.tracking_code, 80),
            ("carrier_code", self.carrier_code, 32),
        ):
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= maximum
                or value != value.strip()
            ):
                raise ValueError(f"{name} must contain trimmed text.")

__all__ = [
    "ChannelFee",
    "ChannelFulfillmentUpdate",
    "ChannelOrderItem",
    "ChannelOrderReference",
    "ChannelOrderSnapshot",
    "ChannelOrderStatus",
    "ChannelSkuMapping",
    "ExternalChannelOrder",
    "ExternalChannelOrderItem",
    "Marketplace",
    "SalesChannelAccount",
]
