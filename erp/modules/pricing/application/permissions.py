"""Official pricing permissions evaluated through the public M1 contract."""

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

PRICING_SIMULATE = PermissionCode("pricing.price.simulate")
PRICING_PRICE_CREATE = PermissionCode("pricing.price.create")
PRICING_PRICE_ACTIVATE = PermissionCode("pricing.price.activate")
PRICING_MARGIN_VIEW_SENSITIVE = PermissionCode("pricing.margin.view")
PRICING_EXCEPTION_REQUEST = PermissionCode("pricing.exception.request")


def pricing_permission_registry() -> PermissionRegistry:
    return PermissionRegistry(
        Permission(
            code=code,
            description=description,
            risk_level=risk,
            data_classification=classification,
        )
        for code, description, risk, classification in (
            (
                PRICING_SIMULATE,
                "Simulate pricing decisions",
                PermissionRiskLevel.LOW,
                DataClassification.CONFIDENTIAL,
            ),
            (
                PRICING_PRICE_CREATE,
                "Create price lists and draft price versions",
                PermissionRiskLevel.HIGH,
                DataClassification.CONFIDENTIAL,
            ),
            (
                PRICING_PRICE_ACTIVATE,
                "Activate approved price versions",
                PermissionRiskLevel.CRITICAL,
                DataClassification.CONFIDENTIAL,
            ),
            (
                PRICING_MARGIN_VIEW_SENSITIVE,
                "View sensitive pricing margins and cost context",
                PermissionRiskLevel.CRITICAL,
                DataClassification.RESTRICTED,
            ),
            (
                PRICING_EXCEPTION_REQUEST,
                "Request pricing exceptions for approval",
                PermissionRiskLevel.HIGH,
                DataClassification.CONFIDENTIAL,
            ),
        )
    )


class PricingAuthorization:
    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(pricing_permission_registry())

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
    "PRICING_EXCEPTION_REQUEST",
    "PRICING_MARGIN_VIEW_SENSITIVE",
    "PRICING_PRICE_ACTIVATE",
    "PRICING_PRICE_CREATE",
    "PRICING_SIMULATE",
    "PricingAuthorization",
    "pricing_permission_registry",
]
