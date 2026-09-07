"""Ports required by corporate application queries."""

from typing import Protocol

from erp.modules.admin.domain import Branch, Company, CorporateStatus, EconomicGroup, TenantContext


class CompanyDirectory(Protocol):
    """Minimum tenant-filtered company read capability."""

    async def list_companies(
        self,
        context: TenantContext,
        *,
        status: CorporateStatus | None = None,
    ) -> tuple[Company, ...]: ...


class CorporateDirectory(CompanyDirectory, Protocol):
    """Complete tenant-filtered corporate hierarchy capability."""

    async def list_groups(
        self,
        context: TenantContext,
        *,
        status: CorporateStatus | None = None,
    ) -> tuple[EconomicGroup, ...]: ...

    async def list_branches(
        self,
        context: TenantContext,
        *,
        status: CorporateStatus | None = None,
    ) -> tuple[Branch, ...]: ...


__all__ = ["CompanyDirectory", "CorporateDirectory"]
