"""Transaction-owning adapter for corporate application queries."""

from erp.modules.admin.domain import Company, CorporateStatus, TenantContext
from erp.modules.admin.infrastructure.corporate_directory_repository import (
    CorporateDirectoryRepository,
)
from erp.platform.database import Database


class PostgresCorporateDirectory:
    """Adapt caller-neutral queries to short read-only database sessions."""

    def __init__(
        self,
        database: Database,
        repository: CorporateDirectoryRepository | None = None,
    ) -> None:
        self._database = database
        self._repository = repository or CorporateDirectoryRepository()

    async def list_companies(
        self,
        context: TenantContext,
        *,
        status: CorporateStatus | None = None,
    ) -> tuple[Company, ...]:
        async with self._database.session() as session:
            companies = await self._repository.list_companies(session, context, status=status)
        return tuple(companies)


__all__ = ["PostgresCorporateDirectory"]
