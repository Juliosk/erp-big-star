"""Authorization at every use case, including download, history and replay."""

from typing import Any, Protocol
from uuid import UUID

from erp.modules.admin.contracts import (
    AuthorizationPolicy,
    CompanyAccessService,
    DataClassification,
    Permission,
    PermissionCode,
    PermissionRegistry,
    PermissionRiskLevel,
    SecurityContext,
    require_permission,
)
from erp.modules.product.contracts import PRODUCT_READ, CommandMetadata, ProductAuthorization

IMPORT_EXECUTE = PermissionCode("data.import.execute")
IMPORT_CONFIRM = PermissionCode("data.import.confirm")


class ImportStore(Protocol):
    async def templates(self, company_id: UUID) -> list[dict[str, Any]]: ...
    async def download(self, company_id: UUID, template_id: UUID, version: int) -> bytes: ...
    async def provision(
        self, company_id: UUID, actor_id: UUID, metadata: CommandMetadata
    ) -> dict[str, Any]: ...
    async def upload(
        self,
        context: SecurityContext,
        company_id: UUID,
        template_id: UUID,
        version: int,
        filename: str,
        content: bytes,
        key: str,
        metadata: CommandMetadata,
    ) -> dict[str, Any]: ...
    async def history(self, company_id: UUID, page: int) -> list[dict[str, Any]]: ...
    async def get(self, company_id: UUID, job_id: UUID) -> dict[str, Any]: ...
    async def command(
        self,
        context: SecurityContext,
        company_id: UUID,
        job_id: UUID,
        action: str,
        version: int,
        fingerprint: str,
        key: str,
        metadata: CommandMetadata,
    ) -> dict[str, Any]: ...


class ImportService:
    def __init__(self, store: ImportStore, companies: CompanyAccessService) -> None:
        self.store = store
        self._companies = companies
        self._products = ProductAuthorization(companies)
        self._policy = AuthorizationPolicy(
            PermissionRegistry(
                Permission(
                    code=code,
                    description="Governed product import",
                    risk_level=PermissionRiskLevel.HIGH,
                    data_classification=DataClassification.CONFIDENTIAL,
                )
                for code in (IMPORT_EXECUTE, IMPORT_CONFIRM)
            )
        )

    async def authorize(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        confirm: bool = False,
        write: bool = False,
    ) -> None:
        require_permission(policy=self._policy, context=context, permission=IMPORT_EXECUTE)
        if confirm:
            require_permission(policy=self._policy, context=context, permission=IMPORT_CONFIRM)
        await self._companies.require_company(context, company_id, write=write)
        await self._products.require(context, company_id, PRODUCT_READ)


__all__ = ["IMPORT_CONFIRM", "IMPORT_EXECUTE", "ImportService", "ImportStore"]
