"""M6 permission registry contract."""

from erp.modules.admin.contracts import DataClassification, PermissionRiskLevel
from erp.modules.procurement.application import (
    PROCUREMENT_MATCHING_EXECUTE,
    PROCUREMENT_MATCHING_READ,
    PROCUREMENT_ORDER_MANAGE,
    PROCUREMENT_ORDER_READ,
    PROCUREMENT_RECEIPT_MANAGE,
    PROCUREMENT_RECEIPT_READ,
    PROCUREMENT_REQUISITION_MANAGE,
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
        PROCUREMENT_REQUISITION_READ,
        PROCUREMENT_REQUISITION_MANAGE,
        PROCUREMENT_ORDER_READ,
        PROCUREMENT_ORDER_MANAGE,
        PROCUREMENT_RECEIPT_READ,
        PROCUREMENT_RECEIPT_MANAGE,
        PROCUREMENT_MATCHING_READ,
        PROCUREMENT_MATCHING_EXECUTE,
    }

    assert frozenset(item.code for item in registry.all()) == frozenset(expected)
    assert all(len(str(code).split(".")) == 3 for code in expected)
    assert all(
        registry.get(code).data_classification is DataClassification.CONFIDENTIAL
        for code in expected
    )


def test_procurement_mutation_risks_are_fail_closed() -> None:
    registry = procurement_permission_registry()

    assert registry.get(PROCUREMENT_SUPPLIER_MANAGE).risk_level is PermissionRiskLevel.HIGH
    assert registry.get(PROCUREMENT_ORDER_MANAGE).risk_level is PermissionRiskLevel.HIGH
    assert registry.get(PROCUREMENT_MATCHING_EXECUTE).risk_level is PermissionRiskLevel.CRITICAL
