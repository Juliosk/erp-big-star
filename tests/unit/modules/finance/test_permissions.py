"""M12 accounts-payable permission matrix."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import (
    CompanyAccessService,
    DataClassification,
    PermissionRiskLevel,
    SecurityContext,
)
from erp.modules.finance.application import (
    FINANCE_PAYABLE_ADJUST,
    FINANCE_PAYABLE_APPROVE,
    FINANCE_PAYABLE_CREATE,
    FINANCE_PAYABLE_READ,
    FINANCE_TREASURY_BATCH_APPROVE,
    FINANCE_TREASURY_BATCH_CREATE,
    FINANCE_TREASURY_BATCH_EXECUTE,
    FINANCE_TREASURY_READ,
    FinanceAuthorization,
    finance_permission_registry,
)
from erp.modules.finance.application import permissions as permission_module


def test_finance_registry_exposes_canonical_payable_and_treasury_permissions() -> None:
    registry = finance_permission_registry()
    expected = {
        FINANCE_PAYABLE_READ,
        FINANCE_PAYABLE_CREATE,
        FINANCE_PAYABLE_APPROVE,
        FINANCE_PAYABLE_ADJUST,
        FINANCE_TREASURY_READ,
        FINANCE_TREASURY_BATCH_CREATE,
        FINANCE_TREASURY_BATCH_APPROVE,
        FINANCE_TREASURY_BATCH_EXECUTE,
    }

    assert frozenset(item.code for item in registry.all()) == frozenset(expected)
    assert all(len(str(code).split(".")) == 3 for code in expected)
    assert all(
        registry.get(code).data_classification is DataClassification.RESTRICTED for code in expected
    )


def test_finance_sensitive_operations_are_fail_closed_by_risk() -> None:
    registry = finance_permission_registry()

    assert registry.get(FINANCE_PAYABLE_READ).risk_level is PermissionRiskLevel.HIGH
    assert registry.get(FINANCE_PAYABLE_CREATE).risk_level is PermissionRiskLevel.HIGH
    assert registry.get(FINANCE_PAYABLE_APPROVE).risk_level is PermissionRiskLevel.CRITICAL
    assert registry.get(FINANCE_PAYABLE_ADJUST).risk_level is PermissionRiskLevel.CRITICAL
    assert registry.get(FINANCE_TREASURY_READ).risk_level is PermissionRiskLevel.HIGH
    assert registry.get(FINANCE_TREASURY_BATCH_CREATE).risk_level is PermissionRiskLevel.CRITICAL
    assert registry.get(FINANCE_TREASURY_BATCH_APPROVE).risk_level is PermissionRiskLevel.CRITICAL
    assert registry.get(FINANCE_TREASURY_BATCH_EXECUTE).risk_level is PermissionRiskLevel.CRITICAL


def test_finance_authorization_requires_permission_and_company_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company_id = uuid4()
    calls: list[tuple[str, object]] = []

    class Companies:
        async def require_company(
            self, context: SecurityContext, received_company_id: UUID, *, write: bool
        ) -> None:
            calls.append(("company", (context, received_company_id, write)))

    context = cast(SecurityContext, object())

    def require_permission(**kwargs: object) -> None:
        calls.append(("permission", kwargs))

    monkeypatch.setattr(permission_module, "require_permission", require_permission)
    authorization = FinanceAuthorization(cast(CompanyAccessService, Companies()))

    asyncio.run(
        authorization.require(
            context,
            company_id,
            FINANCE_PAYABLE_CREATE,
            write=True,
        )
    )

    assert [name for name, _ in calls] == ["permission", "company"]
    assert calls[1][1] == (context, company_id, True)
