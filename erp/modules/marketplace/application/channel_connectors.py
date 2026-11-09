"""M3 transport port implemented by OAuth-aware marketplace adapters."""

from collections.abc import Mapping
from typing import Protocol

from erp.modules.sales.contracts import ChannelOrderReference, ExternalChannelOrder


class ChannelConnector(Protocol):
    """Fetch or normalize an order using credentials held by the adapter.

    Unknown SKU mappings/statuses fail closed. Implementations must verify
    response scope and preserve original external identities and amounts.
    """

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


__all__ = ["ChannelConnector"]
