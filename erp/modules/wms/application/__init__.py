"""Application services and policies for M10 WMS."""

from erp.modules.wms.application.permissions import (
    WMS_DISPATCH_EXECUTE,
    WMS_LABEL_REPRINT,
    WMS_PACK_EXECUTE,
    WMS_PICK_EXECUTE,
    WMS_SHORTAGE_OVERRIDE,
    WmsAuthorization,
    wms_permission_registry,
)

__all__ = [
    "WMS_DISPATCH_EXECUTE",
    "WMS_LABEL_REPRINT",
    "WMS_PACK_EXECUTE",
    "WMS_PICK_EXECUTE",
    "WMS_SHORTAGE_OVERRIDE",
    "WmsAuthorization",
    "wms_permission_registry",
]

