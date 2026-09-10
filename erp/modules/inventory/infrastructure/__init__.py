"""Internal M5 persistence adapters, wired only at the composition boundary."""

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
from erp.modules.inventory.infrastructure.warehouse_model import (
    WarehouseLocationModel,
    WarehouseModel,
)

__all__ = [
    "InventoryBalanceModel",
    "InventoryBalanceRepository",
    "InventoryLedgerRepository",
    "InventoryLotModel",
    "InventoryLotRepository",
    "InventoryPoolModel",
    "InventoryPoolRepository",
    "InventoryPostingModel",
    "InventoryTransactionModel",
    "LocationRepository",
    "LotRepository",
    "PoolRepository",
    "PostgresInventoryBalances",
    "PostgresInventoryCatalog",
    "PostgresInventoryCatalogue",
    "PostgresInventoryDirectory",
    "WarehouseLocationModel",
    "WarehouseLocationRepository",
    "WarehouseModel",
    "WarehouseRepository",
]
