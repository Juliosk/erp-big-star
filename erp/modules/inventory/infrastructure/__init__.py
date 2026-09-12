"""Internal M5 persistence adapters, wired only at the composition boundary."""

from erp.modules.inventory.infrastructure.adjustment_effects import InventoryAdjustmentEffects
from erp.modules.inventory.infrastructure.adjustments import PostgresInventoryAdjustments
from erp.modules.inventory.infrastructure.balance_model import InventoryBalanceModel
from erp.modules.inventory.infrastructure.balance_repository import InventoryBalanceRepository
from erp.modules.inventory.infrastructure.balances import PostgresInventoryBalances
from erp.modules.inventory.infrastructure.catalogue import (
    PostgresInventoryCatalog,
    PostgresInventoryCatalogue,
    PostgresInventoryDirectory,
)
from erp.modules.inventory.infrastructure.ledger_model import (
    InventoryPostingModel,
    InventoryTransactionModel,
)
from erp.modules.inventory.infrastructure.ledger_repository import InventoryLedgerRepository
from erp.modules.inventory.infrastructure.lot_model import InventoryLotModel
from erp.modules.inventory.infrastructure.movement_projection import (
    INVENTORY_ADJUSTED,
    INVENTORY_MOVEMENT_PROJECTOR,
    InventoryMovementProjectionConsumer,
    InventoryMovementProjectionModel,
)
from erp.modules.inventory.infrastructure.movement_transport import (
    INVENTORY_ADJUSTED_ROUTING_KEY,
    RabbitInventoryMovementTransport,
)
from erp.modules.inventory.infrastructure.pool_model import InventoryPoolModel
from erp.modules.inventory.infrastructure.repository import (
    InventoryLotRepository,
    InventoryPoolRepository,
    LocationRepository,
    LotRepository,
    PoolRepository,
    WarehouseLocationRepository,
    WarehouseRepository,
)
from erp.modules.inventory.infrastructure.reservation_model import (
    InventoryReservationAllocationModel,
    InventoryReservationModel,
)
from erp.modules.inventory.infrastructure.reservations import PostgresInventoryReservations
from erp.modules.inventory.infrastructure.warehouse_model import (
    WarehouseLocationModel,
    WarehouseModel,
)

__all__ = [
    "INVENTORY_ADJUSTED",
    "INVENTORY_ADJUSTED_ROUTING_KEY",
    "INVENTORY_MOVEMENT_PROJECTOR",
    "InventoryAdjustmentEffects",
    "InventoryBalanceModel",
    "InventoryBalanceRepository",
    "InventoryLedgerRepository",
    "InventoryLotModel",
    "InventoryLotRepository",
    "InventoryMovementProjectionConsumer",
    "InventoryMovementProjectionModel",
    "InventoryPoolModel",
    "InventoryPoolRepository",
    "InventoryPostingModel",
    "InventoryReservationAllocationModel",
    "InventoryReservationModel",
    "InventoryTransactionModel",
    "LocationRepository",
    "LotRepository",
    "PoolRepository",
    "PostgresInventoryAdjustments",
    "PostgresInventoryBalances",
    "PostgresInventoryCatalog",
    "PostgresInventoryCatalogue",
    "PostgresInventoryDirectory",
    "PostgresInventoryReservations",
    "RabbitInventoryMovementTransport",
    "WarehouseLocationModel",
    "WarehouseLocationRepository",
    "WarehouseModel",
    "WarehouseRepository",
]
