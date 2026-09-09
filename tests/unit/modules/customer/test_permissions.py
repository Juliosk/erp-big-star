"""M14 RBAC registry stays explicit and default-deny."""

from erp.modules.admin.domain import DataClassification, PermissionRiskLevel
from erp.modules.customer.application.permissions import (
    CONSENT_MANAGE,
    CUSTOMER_CREATE,
    CUSTOMER_MERGE,
    CUSTOMER_READ,
    CUSTOMER_UPDATE,
    customer_permission_registry,
)


def test_customer_permission_registry_contains_official_codes() -> None:
    registry = customer_permission_registry()

    assert [str(permission.code) for permission in registry.all()] == [
        "crm.consent.manage",
        "crm.customer.create",
        "crm.customer.merge",
        "crm.customer.read",
        "crm.customer.update",
    ]
    assert all(
        permission.data_classification is DataClassification.PERSONAL_DATA
        for permission in registry.all()
    )
    assert registry.get(CUSTOMER_READ).risk_level is PermissionRiskLevel.LOW
    assert registry.get(CUSTOMER_CREATE).risk_level is PermissionRiskLevel.HIGH
    assert registry.get(CUSTOMER_UPDATE).risk_level is PermissionRiskLevel.HIGH
    assert registry.get(CUSTOMER_MERGE).risk_level is PermissionRiskLevel.CRITICAL
    assert registry.get(CONSENT_MANAGE).risk_level is PermissionRiskLevel.HIGH
