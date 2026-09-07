"""PostgreSQL repository for operational branches."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from erp.modules.admin.domain import Branch
from erp.modules.admin.infrastructure.corporate_mapping import branch_from_model
from erp.modules.admin.infrastructure.corporate_models import BranchModel
from erp.platform.concurrency import OptimisticLockError


class BranchRepository:
    """Persist branches inside caller-owned transactions."""

    async def add(
        self,
        session: AsyncSession,
        branch: Branch,
        *,
        actor_id: UUID | None,
    ) -> None:
        """Stage one new aggregate without committing."""
        session.add(
            BranchModel(
                id=branch.id,
                company_id=branch.company_id,
                code=branch.code,
                name=branch.name,
                tax_id=str(branch.tax_id),
                timezone=branch.timezone,
                status=branch.status,
                version=branch.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await session.flush()

    async def get(self, session: AsyncSession, branch_id: UUID) -> Branch | None:
        """Load one branch by technical identity."""
        result = await session.scalars(select(BranchModel).where(BranchModel.id == branch_id))
        model = result.one_or_none()
        return None if model is None else branch_from_model(model)

    async def save(
        self,
        session: AsyncSession,
        branch: Branch,
        *,
        actor_id: UUID | None,
    ) -> Branch:
        """Persist exactly the next aggregate version or raise a stable conflict."""
        model = await session.get(BranchModel, branch.id)
        expected_version = branch.version - 1
        if model is None or model.version != expected_version:
            raise OptimisticLockError(expected_version=expected_version)
        model.company_id = branch.company_id
        model.code = branch.code
        model.name = branch.name
        model.tax_id = str(branch.tax_id)
        model.timezone = branch.timezone
        model.status = branch.status
        model.updated_at = datetime.now(UTC)
        model.updated_by = actor_id
        try:
            await session.flush()
        except StaleDataError as error:
            raise OptimisticLockError(expected_version=expected_version) from error
        return branch_from_model(model)


__all__ = ["BranchRepository"]
