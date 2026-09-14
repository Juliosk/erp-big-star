"""Official M22 Workflow permissions evaluated through the public M1 contract."""

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

WORKFLOW_REQUEST_READ = PermissionCode("workflow.request.read")
WORKFLOW_REQUEST_CREATE = PermissionCode("workflow.request.create")
WORKFLOW_APPROVAL_DECIDE = PermissionCode("workflow.approval.decide")
WORKFLOW_DEFINITION_MANAGE = PermissionCode("workflow.definition.manage")


def workflow_permission_registry() -> PermissionRegistry:
    return PermissionRegistry(
        Permission(
            code=code,
            description=description,
            risk_level=risk,
            data_classification=classification,
        )
        for code, description, risk, classification in (
            (
                WORKFLOW_REQUEST_READ,
                "Read workflow requests and pending approvals",
                PermissionRiskLevel.MEDIUM,
                DataClassification.CONFIDENTIAL,
            ),
            (
                WORKFLOW_REQUEST_CREATE,
                "Create formal workflow approval requests",
                PermissionRiskLevel.HIGH,
                DataClassification.CONFIDENTIAL,
            ),
            (
                WORKFLOW_APPROVAL_DECIDE,
                "Approve or reject active workflow steps",
                PermissionRiskLevel.CRITICAL,
                DataClassification.CONFIDENTIAL,
            ),
            (
                WORKFLOW_DEFINITION_MANAGE,
                "Manage workflow definitions and approval policies",
                PermissionRiskLevel.CRITICAL,
                DataClassification.RESTRICTED,
            ),
        )
    )


class WorkflowAuthorization:
    def __init__(self, companies: CompanyAccessService) -> None:
        self._companies = companies
        self._policy = AuthorizationPolicy(workflow_permission_registry())

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
    "WORKFLOW_APPROVAL_DECIDE",
    "WORKFLOW_DEFINITION_MANAGE",
    "WORKFLOW_REQUEST_CREATE",
    "WORKFLOW_REQUEST_READ",
    "WorkflowAuthorization",
    "workflow_permission_registry",
]
