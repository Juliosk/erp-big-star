"""M6 permission registry contract."""

from erp.modules.admin.contracts import DataClassification, PermissionRiskLevel
from erp.modules.procurement.application import (
    PROCUREMENT_PURCHASE_ORDER_CHANGE,
    PROCUREMENT_PURCHASE_ORDER_CREATE,
    PROCUREMENT_PURCHASE_ORDER_READ,
    PROCUREMENT_PURCHASE_ORDER_SUBMIT,
    PROCUREMENT_REQUISITION_CREATE,
    PROCUREMENT_REQUISITION_READ,
    PROCUREMENT_SUPPLIER_MANAGE,
    PROCUREMENT_SUPPLIER_READ,
    procurement_permission_registry,
)


def test_procurement_registry_exposes_the_canonical_m6_permissions() -> None:
    registry = procurement_permission_registry()
    expected = {
        PROCUREMENT_SUPPLIER_READ,
        PROCUREMENT_SUPPLIER_MANAGE,
        PROCUREMENT_REQUISITION_CREATE,
        PROCUREMENT_REQUISITION_READ,
        PROCUREMENT_PURCHASE_ORDER_CREATE,
        PROCUREMENT_PURCHASE_ORDER_READ,
        PROCUREMENT_PURCHASE_ORDER_CHANGE,
        PROCUREMENT_PURCHASE_ORDER_SUBMIT,
    }

    assert frozenset(item.code for item in registry.all()) == frozenset(expected)
    assert all(len(str(code).split(".")) == 3 for code in expected)
    assert all(
        registry.get(code).data_classification is DataClassification.CONFIDENTIAL
        for code in expected
    )


def test_procurement_mutation_risks_are_fail_closed() -> None:
    registry = procurement_permission_registry()

    assert (
        registry.get(PROCUREMENT_SUPPLIER_MANAGE).risk_level
        is PermissionRiskLevel.HIGH
    )
    assert (
        registry.get(PROCUREMENT_PURCHASE_ORDER_CHANGE).risk_level
        is PermissionRiskLevel.HIGH
    )
    assert (
        registry.get(PROCUREMENT_PURCHASE_ORDER_SUBMIT).risk_level
        is PermissionRiskLevel.CRITICAL
    )
