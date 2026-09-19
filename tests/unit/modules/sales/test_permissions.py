"""M15 permission registry contract."""

from erp.modules.sales.application import (
    SALES_CUSTOMER_PORTFOLIO_READ,
    SALES_DISCOUNT_REQUEST,
    SALES_QUOTE_CONVERT,
    SALES_QUOTE_CREATE,
    SALES_QUOTE_READ,
    SALES_QUOTE_SEND,
    SALES_QUOTE_UPDATE,
    sales_permission_registry,
)


def test_sales_registry_exposes_only_canonical_three_segment_permissions() -> None:
    registry = sales_permission_registry()
    codes = (
        SALES_CUSTOMER_PORTFOLIO_READ,
        SALES_DISCOUNT_REQUEST,
        SALES_QUOTE_CONVERT,
        SALES_QUOTE_CREATE,
        SALES_QUOTE_READ,
        SALES_QUOTE_SEND,
        SALES_QUOTE_UPDATE,
    )
    assert all(registry.get(code) is not None for code in codes)
    assert all(len(str(code).split(".")) == 3 for code in codes)
    assert registry.get(SALES_QUOTE_CONVERT).risk_level == "CRITICAL"
