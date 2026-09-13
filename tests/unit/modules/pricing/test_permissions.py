"""M9 pricing RBAC registry."""

from erp.modules.admin.contracts import DataClassification, PermissionRiskLevel
from erp.modules.pricing.application.permissions import (
    PRICING_MARGIN_VIEW_SENSITIVE,
    PRICING_PRICE_ACTIVATE,
    pricing_permission_registry,
)


def test_pricing_permissions_include_sensitive_margin_gate() -> None:
    registry = pricing_permission_registry()

    margin = registry.get(PRICING_MARGIN_VIEW_SENSITIVE)
    activate = registry.get(PRICING_PRICE_ACTIVATE)

    assert margin.data_classification is DataClassification.RESTRICTED
    assert margin.risk_level is PermissionRiskLevel.CRITICAL
    assert activate.risk_level is PermissionRiskLevel.CRITICAL
