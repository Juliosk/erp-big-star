"""Unit tests for roles, scopes, and default-deny authorization."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    AuthorizationPolicy,
    AuthorizationReason,
    DataClassification,
    Permission,
    PermissionCode,
    PermissionRegistry,
    PermissionRiskLevel,
    Role,
    RoleAssignment,
    RoleAssignmentSource,
    Scope,
    ScopeType,
    resolve_active_permissions,
)

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
USER_ID = uuid4()
ROLE_ID = uuid4()
COMPANY_SCOPE = Scope(ScopeType.COMPANY, uuid4())
READ_USERS = PermissionCode("admin.user.read")


def registered_permission(
    *,
    step_up: AuthenticationLevel | None = None,
) -> Permission:
    return Permission(
        code=READ_USERS,
        description="Read users",
        risk_level=PermissionRiskLevel.LOW,
        data_classification=DataClassification.PERSONAL_DATA,
        step_up_default=step_up,
    )


def principal(level: AuthenticationLevel = AuthenticationLevel.LEVEL_1) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(USER_ID, uuid4(), level)


def test_role_assignments_compose_only_active_role_permissions() -> None:
    role = Role(ROLE_ID, "USER_ADMIN", "User administrator", frozenset({READ_USERS}))
    assignments = [
        RoleAssignment(
            USER_ID,
            ROLE_ID,
            NOW - timedelta(days=1),
            None,
            RoleAssignmentSource.MANUAL,
        ),
        RoleAssignment(
            uuid4(),
            ROLE_ID,
            NOW - timedelta(days=1),
            None,
            RoleAssignmentSource.JOB_BASED,
        ),
        RoleAssignment(
            USER_ID,
            ROLE_ID,
            NOW - timedelta(days=2),
            NOW - timedelta(days=1),
            RoleAssignmentSource.TEMPORARY,
        ),
    ]

    granted = resolve_active_permissions(
        user_id=USER_ID,
        roles={ROLE_ID: role},
        assignments=assignments,
        instant=NOW,
    )

    assert granted == frozenset({READ_USERS})


@pytest.mark.parametrize(
    ("principal_value", "permissions", "scope", "scopes", "reason"),
    [
        (None, frozenset(), COMPANY_SCOPE, frozenset(), AuthorizationReason.UNAUTHENTICATED),
        (
            principal(),
            frozenset(),
            COMPANY_SCOPE,
            frozenset({COMPANY_SCOPE}),
            AuthorizationReason.PERMISSION_NOT_GRANTED,
        ),
        (
            principal(),
            frozenset({READ_USERS}),
            None,
            frozenset({COMPANY_SCOPE}),
            AuthorizationReason.SCOPE_REQUIRED,
        ),
        (
            principal(),
            frozenset({READ_USERS}),
            COMPANY_SCOPE,
            frozenset(),
            AuthorizationReason.SCOPE_NOT_GRANTED,
        ),
    ],
)
def test_authorization_denies_without_every_required_dimension(
    principal_value: AuthenticatedPrincipal | None,
    permissions: frozenset[PermissionCode],
    scope: Scope | None,
    scopes: frozenset[Scope],
    reason: AuthorizationReason,
) -> None:
    policy = AuthorizationPolicy(PermissionRegistry([registered_permission()]))

    decision = policy.decide(
        principal=principal_value,
        required_permission=READ_USERS,
        granted_permissions=permissions,
        required_scope=scope,
        granted_scopes=scopes,
    )

    assert decision.allowed is False
    assert decision.reason is reason


def test_authorization_denies_permission_absent_from_registry() -> None:
    decision = AuthorizationPolicy(PermissionRegistry()).decide(
        principal=principal(),
        required_permission=READ_USERS,
        granted_permissions=frozenset({READ_USERS}),
        required_scope=COMPANY_SCOPE,
        granted_scopes=frozenset({COMPANY_SCOPE}),
    )

    assert decision.reason is AuthorizationReason.PERMISSION_NOT_REGISTERED


def test_authorization_requires_step_up_and_then_grants() -> None:
    policy = AuthorizationPolicy(
        PermissionRegistry([registered_permission(step_up=AuthenticationLevel.LEVEL_3)])
    )
    denied = policy.decide(
        principal=principal(AuthenticationLevel.LEVEL_1),
        required_permission=READ_USERS,
        granted_permissions=frozenset({READ_USERS}),
        required_scope=COMPANY_SCOPE,
        granted_scopes=frozenset({COMPANY_SCOPE}),
    )
    granted = policy.decide(
        principal=principal(AuthenticationLevel.LEVEL_3),
        required_permission=READ_USERS,
        granted_permissions=frozenset({READ_USERS}),
        required_scope=COMPANY_SCOPE,
        granted_scopes=frozenset({COMPANY_SCOPE}),
    )

    assert denied.reason is AuthorizationReason.STEP_UP_REQUIRED
    assert granted.allowed is True
    assert granted.reason is AuthorizationReason.GRANTED
