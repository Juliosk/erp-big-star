"""Official M15 permissions evaluated through public M1 contracts."""

from uuid import UUID

from erp.modules.admin.contracts import (
    AuthorizationPolicy,
    CompanyAccessService,
    DataClassification,
    Permission,
    PermissionCode,
    PermissionRegistry,
    PermissionRiskLevel,
    SecurityContext,
    require_permission,
)

SALES_QUOTE_READ = PermissionCode("sales.quote.read")
SALES_QUOTE_CREATE = PermissionCode("sales.quote.create")
SALES_QUOTE_UPDATE = PermissionCode("sales.quote.update")
SALES_QUOTE_SEND = PermissionCode("sales.quote.send")
SALES_QUOTE_CONVERT = PermissionCode("sales.quote.convert")
SALES_DISCOUNT_REQUEST = PermissionCode("sales.discount.request")
SALES_CUSTOMER_PORTFOLIO_READ = PermissionCode("sales.customer_portfolio.read")
SALES_ORDER_CREATE = PermissionCode("sales.order.create")
SALES_ORDER_READ = PermissionCode("sales.order.read")


def sales_permission_registry() -> PermissionRegistry:
    specifications = (
        (SALES_QUOTE_READ, "Read B2B sales quotes", PermissionRiskLevel.MEDIUM),
        (SALES_QUOTE_CREATE, "Create B2B sales quotes", PermissionRiskLevel.MEDIUM),
        (SALES_QUOTE_UPDATE, "Revise draft sales quotes", PermissionRiskLevel.HIGH),
        (SALES_QUOTE_SEND, "Send sales quotes to customers", PermissionRiskLevel.HIGH),
        (SALES_QUOTE_CONVERT, "Convert accepted quotes into orders", PermissionRiskLevel.CRITICAL),
        (SALES_DISCOUNT_REQUEST, "Request approval for discount exceptions", PermissionRiskLevel.HIGH),
        (
            SALES_CUSTOMER_PORTFOLIO_READ,
            "Read assigned commercial customer portfolio",
            PermissionRiskLevel.MEDIUM,
        ),
        (SALES_ORDER_CREATE, "Create sales orders", PermissionRiskLevel.HIGH),
        (SALES_ORDER_READ, "Read sales orders", PermissionRiskLevel.MEDIUM),
    )
    return PermissionRegistry(
        Permission(
            code=code,
            description=description,
            risk_level=risk,
            data_classification=DataClassification.CONFIDENTIAL,
        )
        for code, description, risk in specifications
    )


class SalesAuthorization:
    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(sales_permission_registry())

    async def require(
        self,
        context: SecurityContext,
        company_id: UUID,
        permission: PermissionCode,
        *,
        write: bool = False,
    ) -> None:
        require_permission(policy=self._policy, context=context, permission=permission)
        await self._companies.require_company(context, company_id, write=write)


__all__ = [
    "SALES_CUSTOMER_PORTFOLIO_READ",
    "SALES_DISCOUNT_REQUEST",
    "SALES_ORDER_CREATE",
    "SALES_ORDER_READ",
    "SALES_QUOTE_CONVERT",
    "SALES_QUOTE_CREATE",
    "SALES_QUOTE_READ",
    "SALES_QUOTE_SEND",
    "SALES_QUOTE_UPDATE",
    "SalesAuthorization",
    "sales_permission_registry",
]
