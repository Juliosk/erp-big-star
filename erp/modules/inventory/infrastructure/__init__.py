"""Internal M5 persistence adapters, wired only at the composition boundary."""

from erp.modules.inventory.infrastructure.lot_model import InventoryLotModel
from erp.modules.inventory.infrastructure.pool_model import InventoryPoolModel
from erp.modules.inventory.infrastructure.warehouse_model import (
    WarehouseLocationModel,
    WarehouseModel,
)

__all__ = [
    "InventoryLotModel",
    "InventoryPoolModel",
    "WarehouseLocationModel",
    "WarehouseModel",
]
