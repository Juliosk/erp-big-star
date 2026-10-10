"""M11 fiscal permission matrix."""

from erp.modules.admin.contracts import DataClassification, PermissionRiskLevel
from erp.modules.fiscal.application import (
    FISCAL_INBOUND_MANAGE,
    FISCAL_INBOUND_READ,
    FISCAL_NFE_CANCEL,
    FISCAL_NFE_CORRECT,
    FISCAL_NFE_ISSUE,
    FISCAL_NFE_READ,
    fiscal_permission_registry,
)


def test_fiscal_registry_exposes_only_canonical_nfe_permissions() -> None:
    registry = fiscal_permission_registry()
    expected = {
        FISCAL_NFE_READ,
        FISCAL_NFE_ISSUE,
        FISCAL_NFE_CANCEL,
        FISCAL_NFE_CORRECT,
        FISCAL_INBOUND_READ,
        FISCAL_INBOUND_MANAGE,
    }

    assert frozenset(item.code for item in registry.all()) == frozenset(expected)
    assert all(len(str(code).split(".")) == 3 for code in expected)
    assert all(
        registry.get(code).data_classification is DataClassification.RESTRICTED
        for code in expected
    )


def test_fiscal_mutations_are_critical_and_read_is_high_risk() -> None:
    registry = fiscal_permission_registry()

    assert registry.get(FISCAL_NFE_READ).risk_level is PermissionRiskLevel.HIGH
    assert registry.get(FISCAL_INBOUND_READ).risk_level is PermissionRiskLevel.HIGH
    for code in (
        FISCAL_NFE_ISSUE,
        FISCAL_NFE_CANCEL,
        FISCAL_NFE_CORRECT,
        FISCAL_INBOUND_MANAGE,
    ):
        assert registry.get(code).risk_level is PermissionRiskLevel.CRITICAL
