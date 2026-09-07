"""Scope-filtered read repository for the corporate hierarchy."""

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from erp.modules.admin.domain import (
    Branch,
    Company,
    CorporateStatus,
    EconomicGroup,
    TenantContext,
)
from erp.modules.admin.infrastructure.corporate_mapping import (
    branch_from_model,
    company_from_model,
    economic_group_from_model,
)
from erp.modules.admin.infrastructure.corporate_models import (
    BranchModel,
    CompanyModel,
    EconomicGroupModel,
)


class CorporateDirectoryRepository:
    """Read corporate nodes only through an explicit, default-deny context."""

    async def list_groups(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        status: CorporateStatus | None = None,
    ) -> list[EconomicGroup]:
        """List directly granted groups plus ancestors of narrower grants."""
        company_parent_groups = select(CompanyModel.group_id).where(
            CompanyModel.id.in_(context.company_ids)
        )
        branch_parent_groups = (
            select(CompanyModel.group_id)
            .join(BranchModel, BranchModel.company_id == CompanyModel.id)
            .where(BranchModel.id.in_(context.branch_ids))
        )
        statement = select(EconomicGroupModel).where(
            or_(
                EconomicGroupModel.id.in_(context.group_ids),
                EconomicGroupModel.id.in_(company_parent_groups),
                EconomicGroupModel.id.in_(branch_parent_groups),
            )
        )
        statement = self._with_status(statement, EconomicGroupModel.status, status)
        rows = await session.scalars(statement.order_by(EconomicGroupModel.code))
        return [economic_group_from_model(row) for row in rows.all()]

    async def list_companies(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        status: CorporateStatus | None = None,
    ) -> list[Company]:
        """List companies granted directly, through a group, or as branch ancestors."""
        branch_parent_companies = select(BranchModel.company_id).where(
            BranchModel.id.in_(context.branch_ids)
        )
        statement = select(CompanyModel).where(
            or_(
                CompanyModel.group_id.in_(context.group_ids),
                CompanyModel.id.in_(context.company_ids),
                CompanyModel.id.in_(branch_parent_companies),
            )
        )
        statement = self._with_status(statement, CompanyModel.status, status)
        rows = await session.scalars(statement.order_by(CompanyModel.code))
        return [company_from_model(row) for row in rows.all()]

    async def list_branches(
        self,
        session: AsyncSession,
        context: TenantContext,
        *,
        status: CorporateStatus | None = None,
    ) -> list[Branch]:
        """List only branches reachable from one of the actor's explicit scopes."""
        statement = (
            select(BranchModel)
            .join(CompanyModel, CompanyModel.id == BranchModel.company_id)
            .where(
                or_(
                    CompanyModel.group_id.in_(context.group_ids),
                    BranchModel.company_id.in_(context.company_ids),
                    BranchModel.id.in_(context.branch_ids),
                )
            )
        )
        statement = self._with_status(statement, BranchModel.status, status)
        rows = await session.scalars(statement.order_by(BranchModel.code))
        return [branch_from_model(row) for row in rows.all()]

    @staticmethod
    def _with_status[Row](
        statement: Select[tuple[Row]],
        status_column: InstrumentedAttribute[str],
        status: CorporateStatus | None,
    ) -> Select[tuple[Row]]:
        if status is None:
            return statement
        return statement.where(status_column == status)


__all__ = ["CorporateDirectoryRepository"]
