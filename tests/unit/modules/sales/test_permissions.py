"""M15 permission registry contract."""

from erp.modules.sales.application import (
    SALES_CHANNELS_INGEST,
    SALES_CHANNELS_MANAGE,
    SALES_CHANNELS_READ,
    SALES_CUSTOMER_PORTFOLIO_READ,
    SALES_DISCOUNT_REQUEST,
    SALES_ORDER_CANCEL,
    SALES_ORDER_RESERVE,
    SALES_ORDERS_READ,
    SALES_ORDERS_WRITE,
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
        SALES_CHANNELS_INGEST,
        SALES_CHANNELS_MANAGE,
        SALES_CHANNELS_READ,
        SALES_ORDERS_READ,
        SALES_ORDERS_WRITE,
        SALES_CUSTOMER_PORTFOLIO_READ,
        SALES_DISCOUNT_REQUEST,
        SALES_QUOTE_CONVERT,
        SALES_QUOTE_CREATE,
        SALES_QUOTE_READ,
        SALES_QUOTE_SEND,
        SALES_QUOTE_UPDATE,
        SALES_ORDER_RESERVE,
        SALES_ORDER_CANCEL,
    )
    assert all(registry.get(code) is not None for code in codes)
    assert all(len(str(code).split(".")) == 3 for code in codes)
    assert registry.get(SALES_QUOTE_CONVERT).risk_level == "CRITICAL"
    assert registry.get(SALES_ORDER_RESERVE).risk_level == "CRITICAL"
    assert registry.get(SALES_ORDER_CANCEL).risk_level == "CRITICAL"
    assert registry.get(SALES_CHANNELS_MANAGE).risk_level == "CRITICAL"
    assert registry.get(SALES_CHANNELS_INGEST).risk_level == "CRITICAL"
    assert registry.get(SALES_ORDERS_WRITE).risk_level == "HIGH"
