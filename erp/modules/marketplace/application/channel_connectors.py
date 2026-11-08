"""M3 transport port: real vendor adapters require a separate integration spike."""

from typing import Protocol

from erp.modules.sales.contracts import ChannelOrderReference, ChannelOrderSnapshot


class ChannelConnector(Protocol):
    """Fetch and normalize an order using scoped credentials held by the adapter.

    Unknown SKU mappings/statuses fail closed. Implementations must verify
    response scope and preserve original external identities and amounts.
    """

    async def fetch_order(self, reference: ChannelOrderReference) -> ChannelOrderSnapshot: ...


__all__ = ["ChannelConnector"]
