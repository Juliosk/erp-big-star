"""Unit tests for permission naming and registry behavior."""

import pytest

from erp.modules.admin.domain import (
    AuthenticationLevel,
    DataClassification,
    DuplicatePermissionError,
    Permission,
    PermissionCode,
    PermissionNotRegisteredError,
    PermissionRegistry,
    PermissionRiskLevel,
)


def permission(
    code: str,
    *,
    risk: PermissionRiskLevel = PermissionRiskLevel.LOW,
) -> Permission:
    return Permission(
        code=PermissionCode(code),
        description=f"Allows {code}",
        risk_level=risk,
        data_classification=DataClassification.PUBLIC_INTERNAL,
    )


def test_permission_code_exposes_standard_segments() -> None:
    code = PermissionCode("admin.user.disable")

    assert code.domain == "admin"
    assert code.resource == "user"
    assert code.action == "disable"
    assert str(code) == "admin.user.disable"


@pytest.mark.parametrize(
    "code",
    [
        "admin.user",
        "admin.user.disable.extra",
        "Admin.user.disable",
        "admin.user-role.manage",
        "admin..manage",
    ],
)
def test_permission_code_rejects_nonstandard_names(code: str) -> None:
    with pytest.raises(ValueError, match=r"<domain>\.<resource>\.<action>"):
        PermissionCode(code)


def test_permission_retains_required_registry_metadata() -> None:
    registered = Permission(
        code=PermissionCode("admin.break_glass.execute"),
        description="Activate emergency privileged access",
        risk_level=PermissionRiskLevel.CRITICAL,
        data_classification=DataClassification.RESTRICTED,
        step_up_default=AuthenticationLevel.LEVEL_3,
    )

    assert registered.domain == "admin"
    assert registered.risk_level is PermissionRiskLevel.CRITICAL
    assert registered.data_classification is DataClassification.RESTRICTED
    assert registered.step_up_default is AuthenticationLevel.LEVEL_3


def test_registry_rejects_duplicate_and_unknown_permissions() -> None:
    registered = permission("admin.user.create")
    registry = PermissionRegistry([registered])

    with pytest.raises(DuplicatePermissionError, match=r"admin\.user\.create"):
        registry.register(registered)
    with pytest.raises(PermissionNotRegisteredError, match=r"admin\.user\.disable"):
        registry.get(PermissionCode("admin.user.disable"))


def test_registry_lists_explicit_permissions_deterministically() -> None:
    role_permission = permission("admin.role.manage", risk=PermissionRiskLevel.HIGH)
    user_permission = permission("admin.user.create")
    product_permission = permission("product.product.read")
    registry = PermissionRegistry([product_permission, user_permission, role_permission])

    assert registry.contains(user_permission.code)
    assert registry.all() == (role_permission, user_permission, product_permission)
    assert registry.for_domain("admin") == (role_permission, user_permission)
    assert registry.for_domain("finance") == ()
