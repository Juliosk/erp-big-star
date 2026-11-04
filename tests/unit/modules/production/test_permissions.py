"""Production RBAC registry contract."""

from erp.modules.admin.contracts import (
    DataClassification,
    PermissionRiskLevel,
)
from erp.modules.production.application import (
    PRODUCTION_ENGINEERING_READ,
    PRODUCTION_ENGINEERING_WRITE,
    PRODUCTION_PLANNING_READ,
    PRODUCTION_PLANNING_RUN,
    PRODUCTION_SHOP_FLOOR_EXECUTE,
    PRODUCTION_SHOP_FLOOR_READ,
    production_permission_registry,
)


def test_production_registry_exposes_canonical_permissions() -> None:
    registry = production_permission_registry()
    expected = {
        PRODUCTION_ENGINEERING_READ,
        PRODUCTION_ENGINEERING_WRITE,
        PRODUCTION_PLANNING_READ,
        PRODUCTION_PLANNING_RUN,
        PRODUCTION_SHOP_FLOOR_READ,
        PRODUCTION_SHOP_FLOOR_EXECUTE,
    }

    assert frozenset(item.code for item in registry.all()) == frozenset(expected)
    assert all(len(str(code).split(".")) == 3 for code in expected)
    assert all(
        registry.get(code).data_classification is DataClassification.CONFIDENTIAL
        for code in expected
    )


def test_production_execution_permissions_are_fail_closed() -> None:
    registry = production_permission_registry()

    assert (
        registry.get(PRODUCTION_ENGINEERING_WRITE).risk_level
        is PermissionRiskLevel.HIGH
    )
    assert registry.get(PRODUCTION_PLANNING_RUN).risk_level is PermissionRiskLevel.CRITICAL
    assert (
        registry.get(PRODUCTION_SHOP_FLOOR_EXECUTE).risk_level
        is PermissionRiskLevel.CRITICAL
    )

