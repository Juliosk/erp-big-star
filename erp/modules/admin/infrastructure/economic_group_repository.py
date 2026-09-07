"""PostgreSQL repository for economic groups."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from erp.modules.admin.domain import EconomicGroup
from erp.modules.admin.infrastructure.corporate_mapping import economic_group_from_model
from erp.modules.admin.infrastructure.corporate_models import EconomicGroupModel
from erp.platform.concurrency import OptimisticLockError


class EconomicGroupRepository:
    """Persist economic groups inside caller-owned transactions."""

    async def add(
        self,
        session: AsyncSession,
        group: EconomicGroup,
        *,
        actor_id: UUID | None,
    ) -> None:
        """Stage one new aggregate without committing."""
        session.add(
            EconomicGroupModel(
                id=group.id,
                code=group.code,
                name=group.name,
                status=group.status,
                version=group.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await session.flush()

    async def get(self, session: AsyncSession, group_id: UUID) -> EconomicGroup | None:
        """Load one group by technical identity."""
        result = await session.scalars(
            select(EconomicGroupModel).where(EconomicGroupModel.id == group_id)
        )
        model = result.one_or_none()
        return None if model is None else economic_group_from_model(model)

    async def save(
        self,
        session: AsyncSession,
        group: EconomicGroup,
        *,
        actor_id: UUID | None,
    ) -> EconomicGroup:
        """Persist exactly the next aggregate version or raise a stable conflict."""
        model = await session.get(EconomicGroupModel, group.id)
        expected_version = group.version - 1
        if model is None or model.version != expected_version:
            raise OptimisticLockError(expected_version=expected_version)
        model.code = group.code
        model.name = group.name
        model.status = group.status
        model.updated_at = datetime.now(UTC)
        model.updated_by = actor_id
        try:
            await session.flush()
        except StaleDataError as error:
            raise OptimisticLockError(expected_version=expected_version) from error
        return economic_group_from_model(model)


__all__ = ["EconomicGroupRepository"]
