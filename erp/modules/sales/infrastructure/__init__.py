"""Public M15 persistence adapters."""

from erp.modules.sales.infrastructure.channel_model import (
    ChannelSalesOrderModel,
    ExternalOrderMappingModel,
    SalesChannelConfigModel,
)
from erp.modules.sales.infrastructure.channel_repository import (
    ChannelOrderIngestion,
    ChannelSkuMappingRepository,
    MultichannelSalesOrderRepository,
    SalesChannelConfigRepository,
)
from erp.modules.sales.infrastructure.conversion import PostgresSalesOrderConversion
from erp.modules.sales.infrastructure.discount_approval import PostgresDiscountApproval
from erp.modules.sales.infrastructure.fulfillment import PostgresSalesFulfillment
from erp.modules.sales.infrastructure.fulfillment_effects import (
    MARKETPLACE_FULFILLMENT_SYNC_REQUESTED,
    SalesFulfillmentEffects,
)
from erp.modules.sales.infrastructure.fulfillment_model import (
    SalesFulfillmentLogModel,
    SalesShipmentModel,
)
from erp.modules.sales.infrastructure.fulfillment_repository import (
    SalesShipmentRepository,
)
from erp.modules.sales.infrastructure.lifecycle import PostgresSalesQuoteLifecycle
from erp.modules.sales.infrastructure.multichannel_ingestion import (
    PostgresMultichannelOrderIngestion,
)
from erp.modules.sales.infrastructure.order_cancellation import PostgresSalesOrderCancellation
from erp.modules.sales.infrastructure.order_model import SalesOrderItemModel, SalesOrderModel
from erp.modules.sales.infrastructure.order_repository import SalesOrderRepository
from erp.modules.sales.infrastructure.order_reservation_model import (
    SalesOrderReservationLineModel,
    SalesOrderReservationModel,
)
from erp.modules.sales.infrastructure.order_reservation_repository import (
    SalesOrderReservationRepository,
)
from erp.modules.sales.infrastructure.order_reservations import (
    PostgresSalesOrderReservations,
)
from erp.modules.sales.infrastructure.orders import PostgresSalesOrders
from erp.modules.sales.infrastructure.quote_model import (
    QuoteRevisionItemModel,
    QuoteRevisionModel,
    SalesQuoteModel,
)
from erp.modules.sales.infrastructure.quotes import PostgresSalesQuotes
from erp.modules.sales.infrastructure.repository import SalesQuoteRepository
from erp.modules.sales.infrastructure.reservation_projection import (
    INVENTORY_RESERVATION_EXPIRED,
    SALES_RESERVATION_PROJECTOR,
    SalesOrderReservationProjectionConsumer,
)
from erp.modules.sales.infrastructure.shipping_gateway import (
    HomologationShippingGateway,
)

__all__ = [
    "INVENTORY_RESERVATION_EXPIRED",
    "MARKETPLACE_FULFILLMENT_SYNC_REQUESTED",
    "SALES_RESERVATION_PROJECTOR",
    "ChannelOrderIngestion",
    "ChannelSalesOrderModel",
    "ChannelSkuMappingRepository",
    "ExternalOrderMappingModel",
    "HomologationShippingGateway",
    "MultichannelSalesOrderRepository",
    "PostgresDiscountApproval",
    "PostgresMultichannelOrderIngestion",
    "PostgresSalesFulfillment",
    "PostgresSalesOrderCancellation",
    "PostgresSalesOrderConversion",
    "PostgresSalesOrderReservations",
    "PostgresSalesOrders",
    "PostgresSalesQuoteLifecycle",
    "PostgresSalesQuotes",
    "QuoteRevisionItemModel",
    "QuoteRevisionModel",
    "SalesChannelConfigModel",
    "SalesChannelConfigRepository",
    "SalesFulfillmentEffects",
    "SalesFulfillmentLogModel",
    "SalesOrderItemModel",
    "SalesOrderModel",
    "SalesOrderRepository",
    "SalesOrderReservationLineModel",
    "SalesOrderReservationModel",
    "SalesOrderReservationProjectionConsumer",
    "SalesOrderReservationRepository",
    "SalesQuoteModel",
    "SalesQuoteRepository",
    "SalesShipmentModel",
    "SalesShipmentRepository",
]
