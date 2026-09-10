"""M5 application services and technology-neutral ports."""

from erp.modules.inventory.application.catalogue import (
    InventoryCatalogService,
    InventoryCreationService,
)
from erp.modules.inventory.application.permissions import InventoryAuthorization
from erp.modules.inventory.application.queries import InventoryQueries

__all__ = [
    "InventoryAuthorization",
    "InventoryCatalogService",
    "InventoryCreationService",
    "InventoryQueries",
]
