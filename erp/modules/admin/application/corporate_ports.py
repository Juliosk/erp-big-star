"""Ports required by corporate application queries."""

from typing import Protocol

from erp.modules.admin.domain import Company, CorporateStatus, TenantContext


class CorporateDirectory(Protocol):
    """Tenant-filtered corporate read capability."""

    async def list_companies(
        self,
        context: TenantContext,
        *,
        status: CorporateStatus | None = None,
    ) -> tuple[Company, ...]: ...


__all__ = ["CorporateDirectory"]
