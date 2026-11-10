"""Deterministic channel-managed shipping adapter for local and homologation flows."""

import hashlib

from erp.modules.sales.application.fulfillment import (
    ShippingLabelGateway,
    ShippingLabelRequest,
)
from erp.modules.sales.domain import ShippingLabel


class HomologationShippingGateway(ShippingLabelGateway):
    """Create repeatable label references without external network side effects."""

    def __init__(self) -> None:
        self.requests: list[ShippingLabelRequest] = []
        self._labels: dict[str, ShippingLabel] = {}

    async def create_label(self, request: ShippingLabelRequest) -> ShippingLabel:
        self.requests.append(request)
        existing = self._labels.get(request.idempotency_key)
        if existing is not None:
            return existing
        digest = hashlib.sha256(request.idempotency_key.encode()).hexdigest().upper()
        carrier = f"MKT_{request.marketplace.value}"[:32]
        label = ShippingLabel(
            carrier_code=carrier,
            service_code=request.carrier_service,
            tracking_code=f"TRK{digest[:24]}",
            label_reference=(
                f"label://{request.marketplace.value.lower()}/"
                f"{request.external_order_id}/{digest[:16]}"
            ),
        )
        self._labels[request.idempotency_key] = label
        return label

    @property
    def labels_created(self) -> int:
        return len(self._labels)


__all__ = ["HomologationShippingGateway"]
