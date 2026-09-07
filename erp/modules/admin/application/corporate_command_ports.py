"""Transaction boundary used by corporate creation services."""

from typing import Protocol

from erp.modules.admin.application.corporate_command_dto import (
    BranchCreationResult,
    CompanyCreationResult,
    CreateBranchCommand,
    CreateCompanyCommand,
)
from erp.modules.admin.domain import TenantContext


class CorporateCommandStore(Protocol):
    async def create_company(
        self,
        command: CreateCompanyCommand,
        context: TenantContext,
    ) -> CompanyCreationResult: ...

    async def create_branch(
        self,
        command: CreateBranchCommand,
        context: TenantContext,
    ) -> BranchCreationResult: ...


__all__ = ["CorporateCommandStore"]
