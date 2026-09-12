"""M5 RBAC registry stays explicit and company-scoped."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

from erp.modules.admin.contracts import CompanyAccessService, SecurityContext
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    DataClassification,
    PermissionRiskLevel,
    Scope,
    ScopeType,
)
from erp.modules.inventory.application.permissions import (
    INVENTORY_ADJUSTMENT_CONFIRM,
    INVENTORY_ADJUSTMENT_CREATE,
    INVENTORY_AVAILABILITY_READ,
    INVENTORY_BALANCE_READ,
    INVENTORY_CYCLE_COUNT_MANAGE,
    INVENTORY_RESERVATION_MANAGE,
    INVENTORY_TRANSFER_CREATE,
    InventoryAuthorization,
    inventory_permission_registry,
)


class CompanyAccessStub:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, bool]] = []

    async def require_company(
        self, context: SecurityContext, company_id: UUID, *, write: bool = False
    ) -> None:
        self.calls.append((company_id, write))


def test_inventory_permission_registry_matches_official_m5_codes() -> None:
    registry = inventory_permission_registry()

    assert tuple(permission.code for permission in registry.all()) == (
        INVENTORY_ADJUSTMENT_CONFIRM,
        INVENTORY_ADJUSTMENT_CREATE,
        INVENTORY_AVAILABILITY_READ,
        INVENTORY_BALANCE_READ,
        INVENTORY_CYCLE_COUNT_MANAGE,
        INVENTORY_RESERVATION_MANAGE,
        INVENTORY_TRANSFER_CREATE,
    )
    assert registry.get(INVENTORY_BALANCE_READ).risk_level is PermissionRiskLevel.LOW
    assert registry.get(INVENTORY_AVAILABILITY_READ).risk_level is PermissionRiskLevel.LOW
    assert registry.get(INVENTORY_ADJUSTMENT_CONFIRM).risk_level is PermissionRiskLevel.CRITICAL
    assert (
        registry.get(INVENTORY_ADJUSTMENT_CONFIRM).data_classification
        is DataClassification.CONFIDENTIAL
    )


def test_inventory_authorization_delegates_company_scope_after_permission() -> None:
    async def scenario() -> None:
        company_id = uuid4()
        companies = CompanyAccessStub()
        service = InventoryAuthorization(cast(CompanyAccessService, companies))
        context = SecurityContext(
            principal=AuthenticatedPrincipal(uuid4(), uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset({INVENTORY_BALANCE_READ, INVENTORY_ADJUSTMENT_CREATE}),
            scopes=frozenset({Scope(ScopeType.COMPANY, company_id)}),
        )

        await service.require(
            context,
            company_id,
            INVENTORY_BALANCE_READ,
        )
        await service.require(
            context,
            company_id,
            INVENTORY_ADJUSTMENT_CREATE,
            write=True,
        )

        assert companies.calls == [(company_id, False), (company_id, True)]

    asyncio.run(scenario())
