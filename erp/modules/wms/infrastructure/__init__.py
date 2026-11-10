"""Internal M10 persistence adapters, wired only at the composition boundary."""

from erp.modules.wms.infrastructure.effects import (
    PICKING_TASK_SCANNED,
    PICKING_WAVE_RELEASED,
    WmsEffects,
)
from erp.modules.wms.infrastructure.location_model import (
    WmsAisleModel,
    WmsBayModel,
    WmsBinCapacityModel,
    WmsBinModel,
    WmsLevelModel,
    WmsZoneModel,
)
from erp.modules.wms.infrastructure.location_repository import WMSLocationRepository
from erp.modules.wms.infrastructure.packing import PostgresPackingStore
from erp.modules.wms.infrastructure.picking import PostgresPickingTaskStore
from erp.modules.wms.infrastructure.putaway import PostgresWmsPutawayStore
from erp.modules.wms.infrastructure.putaway_effects import (
    WMS_PUTAWAY_COMPLETED,
    WmsPutawayEffects,
)
from erp.modules.wms.infrastructure.repository import WmsRepository
from erp.modules.wms.infrastructure.waves import PostgresPickingWaveStore
from erp.modules.wms.infrastructure.wms_model import (
    PackageItemModel,
    PackageModel,
    PickingTaskModel,
    PickingWaveModel,
    ShipmentModel,
)

__all__ = [
    "PICKING_TASK_SCANNED",
    "PICKING_WAVE_RELEASED",
    "WMS_PUTAWAY_COMPLETED",
    "PackageItemModel",
    "PackageModel",
    "PickingTaskModel",
    "PickingWaveModel",
    "PostgresPackingStore",
    "PostgresPickingTaskStore",
    "PostgresPickingWaveStore",
    "PostgresWmsPutawayStore",
    "ShipmentModel",
    "WMSLocationRepository",
    "WmsAisleModel",
    "WmsBayModel",
    "WmsBinCapacityModel",
    "WmsBinModel",
    "WmsEffects",
    "WmsLevelModel",
    "WmsPutawayEffects",
    "WmsRepository",
    "WmsZoneModel",
]
