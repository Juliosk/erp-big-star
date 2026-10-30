"""Official M12 permissions evaluated through public M1 contracts."""

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

FINANCE_PAYABLE_READ = PermissionCode("finance.payable.read")
FINANCE_PAYABLE_CREATE = PermissionCode("finance.payable.create")
FINANCE_PAYABLE_APPROVE = PermissionCode("finance.payable.approve")
FINANCE_PAYABLE_ADJUST = PermissionCode("finance.payable.adjust")
FINANCE_TREASURY_READ = PermissionCode("finance.treasury.read")
FINANCE_TREASURY_BATCH_CREATE = PermissionCode("finance.treasury_batch.create")
FINANCE_TREASURY_BATCH_APPROVE = PermissionCode("finance.treasury_batch.approve")
FINANCE_TREASURY_BATCH_EXECUTE = PermissionCode("finance.treasury_batch.execute")
FINANCE_RECONCILIATION_READ = PermissionCode("finance.reconciliation.read")
FINANCE_RECONCILIATION_IMPORT = PermissionCode("finance.reconciliation.import")
FINANCE_RECONCILIATION_EXECUTE = PermissionCode("finance.reconciliation.execute")
FINANCE_CASH_FLOW_READ = PermissionCode("finance.cash_flow.read")
FINANCE_CASH_FLOW_PROJECT = PermissionCode("finance.cash_flow.project")
FINANCE_CASH_FLOW_SCENARIO = PermissionCode("finance.cash_flow.scenario")


def finance_permission_registry() -> PermissionRegistry:
    specifications = (
        (FINANCE_PAYABLE_READ, "Read payable provisions and titles", PermissionRiskLevel.HIGH),
        (FINANCE_PAYABLE_CREATE, "Create payable provisions and titles", PermissionRiskLevel.HIGH),
        (
            FINANCE_PAYABLE_APPROVE,
            "Approve payable provisions under the applicable authority",
            PermissionRiskLevel.CRITICAL,
        ),
        (
            FINANCE_PAYABLE_ADJUST,
            "Adjust payable amounts, due dates and blocks",
            PermissionRiskLevel.CRITICAL,
        ),
        (
            FINANCE_TREASURY_READ,
            "Read treasury batches and payment execution status",
            PermissionRiskLevel.HIGH,
        ),
        (
            FINANCE_TREASURY_BATCH_CREATE,
            "Create payment batches from eligible payable installments",
            PermissionRiskLevel.CRITICAL,
        ),
        (
            FINANCE_TREASURY_BATCH_APPROVE,
            "Approve payment batches under treasury segregation rules",
            PermissionRiskLevel.CRITICAL,
        ),
        (
            FINANCE_TREASURY_BATCH_EXECUTE,
            "Release approved payment batches to a bank adapter",
            PermissionRiskLevel.CRITICAL,
        ),
        (
            FINANCE_RECONCILIATION_READ,
            "Read bank statements and reconciliation status",
            PermissionRiskLevel.HIGH,
        ),
        (
            FINANCE_RECONCILIATION_IMPORT,
            "Import bank statements into company accounts",
            PermissionRiskLevel.CRITICAL,
        ),
        (
            FINANCE_RECONCILIATION_EXECUTE,
            "Execute or override bank reconciliation decisions",
            PermissionRiskLevel.CRITICAL,
        ),
        (
            FINANCE_CASH_FLOW_READ,
            "Read company cash positions and liquidity projections",
            PermissionRiskLevel.HIGH,
        ),
        (
            FINANCE_CASH_FLOW_PROJECT,
            "Generate or refresh authoritative cash-flow projections",
            PermissionRiskLevel.CRITICAL,
        ),
        (
            FINANCE_CASH_FLOW_SCENARIO,
            "Create and compare non-authoritative liquidity scenarios",
            PermissionRiskLevel.CRITICAL,
        ),
    )
    return PermissionRegistry(
        Permission(
            code=code,
            description=description,
            risk_level=risk,
            data_classification=DataClassification.RESTRICTED,
        )
        for code, description, risk in specifications
    )


class FinanceAuthorization:
    """Fail-closed M12 permission and company-scope policy."""

    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(finance_permission_registry())

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
    "FINANCE_CASH_FLOW_PROJECT",
    "FINANCE_CASH_FLOW_READ",
    "FINANCE_CASH_FLOW_SCENARIO",
    "FINANCE_PAYABLE_ADJUST",
    "FINANCE_PAYABLE_APPROVE",
    "FINANCE_PAYABLE_CREATE",
    "FINANCE_PAYABLE_READ",
    "FINANCE_RECONCILIATION_EXECUTE",
    "FINANCE_RECONCILIATION_IMPORT",
    "FINANCE_RECONCILIATION_READ",
    "FINANCE_TREASURY_BATCH_APPROVE",
    "FINANCE_TREASURY_BATCH_CREATE",
    "FINANCE_TREASURY_BATCH_EXECUTE",
    "FINANCE_TREASURY_READ",
    "FinanceAuthorization",
    "finance_permission_registry",
]
