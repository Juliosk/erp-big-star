"""Unit tests for explicit, default-deny tenant context."""

from uuid import uuid4

from erp.modules.admin.domain import Scope, ScopeType, TenantContext


def test_tenant_context_separates_concrete_scope_levels() -> None:
    actor_id = uuid4()
    group_id = uuid4()
    company_id = uuid4()
    branch_id = uuid4()
    context = TenantContext.from_scopes(
        actor_user_id=actor_id,
        scopes=frozenset(
            {
                Scope(ScopeType.GROUP, group_id),
                Scope(ScopeType.COMPANY, company_id),
                Scope(ScopeType.BRANCH, branch_id),
            }
        ),
    )

    assert context.actor_user_id == actor_id
    assert context.group_ids == frozenset({group_id})
    assert context.company_ids == frozenset({company_id})
    assert context.branch_ids == frozenset({branch_id})


def test_tenant_context_does_not_invent_a_global_scope() -> None:
    context = TenantContext.from_scopes(actor_user_id=uuid4(), scopes=frozenset())

    assert context.group_ids == frozenset()
    assert context.company_ids == frozenset()
    assert context.branch_ids == frozenset()
