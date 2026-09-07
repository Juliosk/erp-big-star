"""PostgreSQL repository for legal companies."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from erp.modules.admin.domain import Cnpj, Company, CorporateStatus
from erp.modules.admin.infrastructure.corporate_models import CompanyModel
from erp.platform.concurrency import OptimisticLockError


class CompanyRepository:
    """Persist legal companies inside caller-owned transactions."""

    async def add(
        self,
        session: AsyncSession,
        company: Company,
        *,
        actor_id: UUID | None,
    ) -> None:
        """Stage one new aggregate without committing."""
        session.add(
            CompanyModel(
                id=company.id,
                group_id=company.group_id,
                code=company.code,
                legal_name=company.legal_name,
                trade_name=company.trade_name,
                tax_id=str(company.tax_id),
                timezone=company.timezone,
                status=company.status,
                version=company.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await session.flush()

    async def get(self, session: AsyncSession, company_id: UUID) -> Company | None:
        """Load one company by technical identity."""
        result = await session.scalars(select(CompanyModel).where(CompanyModel.id == company_id))
        model = result.one_or_none()
        return None if model is None else self._to_domain(model)

    async def save(
        self,
        session: AsyncSession,
        company: Company,
        *,
        actor_id: UUID | None,
    ) -> Company:
        """Persist exactly the next aggregate version or raise a stable conflict."""
        model = await session.get(CompanyModel, company.id)
        expected_version = company.version - 1
        if model is None or model.version != expected_version:
            raise OptimisticLockError(expected_version=expected_version)
        model.group_id = company.group_id
        model.code = company.code
        model.legal_name = company.legal_name
        model.trade_name = company.trade_name
        model.tax_id = str(company.tax_id)
        model.timezone = company.timezone
        model.status = company.status
        model.updated_at = datetime.now(UTC)
        model.updated_by = actor_id
        try:
            await session.flush()
        except StaleDataError as error:
            raise OptimisticLockError(expected_version=expected_version) from error
        return self._to_domain(model)

    @staticmethod
    def _to_domain(model: CompanyModel) -> Company:
        return Company(
            id=model.id,
            group_id=model.group_id,
            code=model.code,
            legal_name=model.legal_name,
            trade_name=model.trade_name,
            tax_id=Cnpj(model.tax_id),
            timezone=model.timezone,
            status=CorporateStatus(model.status),
            version=model.version,
        )


__all__ = ["CompanyRepository"]
