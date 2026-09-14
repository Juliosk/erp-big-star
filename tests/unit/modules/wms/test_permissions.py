"""M10 WMS RBAC registry."""

from erp.modules.wms.application import (
    WMS_DISPATCH_EXECUTE,
    WMS_LABEL_REPRINT,
    WMS_PACK_EXECUTE,
    WMS_PICK_EXECUTE,
    WMS_SHORTAGE_OVERRIDE,
    wms_permission_registry,
)


def test_wms_permissions_include_operational_and_audited_actions() -> None:
    registry = wms_permission_registry()

    assert registry.get(WMS_PICK_EXECUTE).description == "Execute WMS picking tasks"
    assert registry.get(WMS_PACK_EXECUTE).description == "Execute WMS packing tasks"
    assert registry.get(WMS_DISPATCH_EXECUTE).description == "Execute WMS dispatch operations"
    assert registry.get(WMS_LABEL_REPRINT).risk_level.value == "CRITICAL"
    assert registry.get(WMS_SHORTAGE_OVERRIDE).risk_level.value == "CRITICAL"

