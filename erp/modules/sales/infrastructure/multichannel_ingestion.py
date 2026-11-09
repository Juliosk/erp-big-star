"""PostgreSQL transaction boundary for marketplace ingestion and M5 holds."""

import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from erp.modules.inventory.contracts import (
    InventoryReservationKindContract,
    OrderReservationLineContract,
    ReserveOrderInventoryContract,
)
from erp.modules.inventory.infrastructure import SessionOrderInventoryReservationGateway
from erp.modules.sales.application.multichannel_ingestion import (
    IngestMultichannelOrder,
    MultichannelOrderIngestionResult,
    MultichannelOrderIngestionStore,
)
from erp.modules.sales.domain import (
    ChannelOrderItem,
    ChannelOrderSnapshot,
    ExternalChannelOrder,
    MultichannelSalesOrder,
    SalesChannelAccount,
)
from erp.modules.sales.infrastructure.channel_effects import MultichannelOrderEffects
from erp.modules.sales.infrastructure.channel_repository import (
    ChannelSkuMappingRepository,
    MultichannelSalesOrderRepository,
    SalesChannelConfigRepository,
)
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail


class PostgresMultichannelOrderIngestion(MultichannelOrderIngestionStore):
    """Persist Sales + reserve M5 + enqueue effects in one transaction."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_channel_account(
        self, company_id: UUID, channel_config_id: UUID
    ) -> SalesChannelAccount | None:
        async with self._database.session() as session:
            return await SalesChannelConfigRepository(session, company_id=company_id).get(
                channel_config_id
            )

    async def ingest(
        self,
        command: IngestMultichannelOrder,
        normalized: ExternalChannelOrder,
        actor_id: UUID,
    ) -> MultichannelOrderIngestionResult:
        async with self._database.session() as session, session.begin():
            mapping_repository = ChannelSkuMappingRepository(session, company_id=command.company_id)
            items: list[ChannelOrderItem] = []
            for external_item in normalized.items:
                entry = await mapping_repository.get_by_listing(
                    channel_config_id=command.channel_config_id,
                    listing_id=external_item.listing_id,
                    variation_id=external_item.variation_id,
                )
                if (
                    entry is None
                    or not entry.active
                    or entry.mapping.external_sku != external_item.external_sku
                ):
                    raise _sku_not_mapped(external_item.external_sku)
                entry.mapping.require_scope(normalized.reference)
                items.append(
                    ChannelOrderItem(
                        external_item_id=external_item.external_item_id,
                        mapping=entry.mapping,
                        quantity=external_item.quantity,
                        unit_price=external_item.unit_price,
                        discount_amount=external_item.discount_amount,
                    )
                )
            snapshot = ChannelOrderSnapshot(
                reference=normalized.reference,
                status=normalized.status,
                items=tuple(items),
                freight_amount=normalized.freight_amount,
                discount_amount=normalized.discount_amount,
                currency=normalized.currency,
            )
            order = MultichannelSalesOrder.capture(
                channel_config_id=command.channel_config_id,
                snapshot=snapshot,
                order_id=_deterministic_order_id(normalized),
            )
            order = MultichannelSalesOrder(
                id=order.id,
                channel_config_id=order.channel_config_id,
                snapshot=order.snapshot,
                source_fingerprint=_source_fingerprint(order, normalized),
                record_version=order.record_version,
            )
            ingestion = await MultichannelSalesOrderRepository(
                session, company_id=command.company_id
            ).ingest(order, actor_id=actor_id)
            inventory = SessionOrderInventoryReservationGateway(session)
            if ingestion.replayed:
                reservation = await inventory.get_order_reservation_by_reference(
                    command.company_id, ingestion.order.id
                )
                if reservation is None:
                    raise RuntimeError("Idempotent channel order replay has no M5 reservation.")
                return MultichannelOrderIngestionResult(
                    order=ingestion.order,
                    reservation=reservation,
                    fees=normalized.fees,
                    event_id=None,
                    inventory_event_id=None,
                    audit_event_id=None,
                    inventory_audit_event_id=None,
                    replayed=True,
                )

            inventory_result = await inventory.reserve_order(
                ReserveOrderInventoryContract(
                    company_id=command.company_id,
                    order_id=order.id,
                    lines=_reservation_lines(order, command.warehouse_id),
                    idempotency_key=command.idempotency_key,
                    request_id=command.metadata.request_id,
                    correlation_id=command.metadata.correlation_id,
                    source_ip=command.metadata.source_ip,
                    reservation_kind=InventoryReservationKindContract.HARD,
                ),
                actor_id,
            )
            event_id, audit_id = await MultichannelOrderEffects().record(
                session,
                order,
                inventory_result.reservation,
                fees=normalized.fees,
                actor_id=actor_id,
                metadata=command.metadata,
            )
            return MultichannelOrderIngestionResult(
                order=order,
                reservation=inventory_result.reservation,
                fees=normalized.fees,
                event_id=event_id,
                inventory_event_id=inventory_result.event_id,
                audit_event_id=audit_id,
                inventory_audit_event_id=inventory_result.audit_event_id,
            )


def _deterministic_order_id(normalized: ExternalChannelOrder) -> UUID:
    reference = normalized.reference
    identity = ":".join(
        (
            str(reference.company_id),
            reference.marketplace.value,
            str(reference.account_id),
            reference.external_order_id,
        )
    )
    return uuid5(NAMESPACE_URL, f"erp:multichannel-order:{identity}")


def _source_fingerprint(order: MultichannelSalesOrder, normalized: ExternalChannelOrder) -> str:
    payload = {
        "order": order.source_fingerprint,
        "fees": [{"code": fee.code, "amount": str(fee.amount)} for fee in normalized.fees],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _reservation_lines(
    order: MultichannelSalesOrder, warehouse_id: UUID
) -> tuple[OrderReservationLineContract, ...]:
    quantities: defaultdict[UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in order.snapshot.items:
        quantities[item.mapping.product_id] += item.quantity
    return tuple(
        OrderReservationLineContract(
            product_id=product_id,
            quantity=quantities[product_id],
            warehouse_id=warehouse_id,
        )
        for product_id in sorted(quantities, key=str)
    )


def _sku_not_mapped(external_sku: str) -> ApplicationError:
    return ApplicationError(
        code="CHANNEL_SKU_NOT_MAPPED",
        message="Marketplace SKU has no active product mapping.",
        status_code=422,
        details=[ErrorDetail(location=["external_sku"], message=external_sku)],
    )


__all__ = ["PostgresMultichannelOrderIngestion"]
