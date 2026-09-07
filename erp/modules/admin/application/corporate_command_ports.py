"""Transaction boundary used by corporate creation services."""

from typing import Protocol

from erp.modules.admin.application.corporate_command_dto import (
    BranchCreationResult,
    BranchUpdateResult,
    CompanyCreationResult,
    CompanyUpdateResult,
    CreateBranchCommand,
    CreateCompanyCommand,
    UpdateBranchCommand,
    UpdateCompanyCommand,
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

    async def update_company(
        self,
        command: UpdateCompanyCommand,
        context: TenantContext,
    ) -> CompanyUpdateResult: ...

    async def update_branch(
        self,
        command: UpdateBranchCommand,
        context: TenantContext,
    ) -> BranchUpdateResult: ...


__all__ = ["CorporateCommandStore"]
