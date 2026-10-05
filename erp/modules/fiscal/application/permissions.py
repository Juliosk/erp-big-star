"""Official M11 permissions evaluated through public M1 contracts."""

from erp.modules.admin.contracts import (
    DataClassification,
    Permission,
    PermissionCode,
    PermissionRegistry,
    PermissionRiskLevel,
)

FISCAL_NFE_READ = PermissionCode("fiscal.nfe.read")
FISCAL_NFE_ISSUE = PermissionCode("fiscal.nfe.issue")
FISCAL_NFE_CANCEL = PermissionCode("fiscal.nfe.cancel")
FISCAL_NFE_CORRECT = PermissionCode("fiscal.nfe.correct")


def fiscal_permission_registry() -> PermissionRegistry:
    specifications = (
        (FISCAL_NFE_READ, "Read fiscal documents and protocols", PermissionRiskLevel.HIGH),
        (FISCAL_NFE_ISSUE, "Issue NF-e and NFC-e", PermissionRiskLevel.CRITICAL),
        (FISCAL_NFE_CANCEL, "Cancel authorized fiscal documents", PermissionRiskLevel.CRITICAL),
        (FISCAL_NFE_CORRECT, "Register fiscal correction letters", PermissionRiskLevel.CRITICAL),
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


__all__ = [
    "FISCAL_NFE_CANCEL",
    "FISCAL_NFE_CORRECT",
    "FISCAL_NFE_ISSUE",
    "FISCAL_NFE_READ",
    "fiscal_permission_registry",
]
