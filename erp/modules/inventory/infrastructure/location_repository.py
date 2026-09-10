"""Location repository compatibility module."""

from erp.modules.inventory.infrastructure.repository import (
    LocationRepository,
    WarehouseLocationRepository,
)

__all__ = ["LocationRepository", "WarehouseLocationRepository"]
