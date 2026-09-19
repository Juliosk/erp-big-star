"""Public M15 application surface."""

from erp.modules.sales.application.permissions import (
    SALES_CUSTOMER_PORTFOLIO_READ,
    SALES_DISCOUNT_REQUEST,
    SALES_QUOTE_CONVERT,
    SALES_QUOTE_CREATE,
    SALES_QUOTE_READ,
    SALES_QUOTE_SEND,
    SALES_QUOTE_UPDATE,
    SalesAuthorization,
    sales_permission_registry,
)

__all__ = [
    "SALES_CUSTOMER_PORTFOLIO_READ",
    "SALES_DISCOUNT_REQUEST",
    "SALES_QUOTE_CONVERT",
    "SALES_QUOTE_CREATE",
    "SALES_QUOTE_READ",
    "SALES_QUOTE_SEND",
    "SALES_QUOTE_UPDATE",
    "SalesAuthorization",
    "sales_permission_registry",
]
