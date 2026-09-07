"""PostgreSQL repository for the versioned temporary entity."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.platform_test.domain import TestEntity, TestEntityStatus
from erp.modules.platform_test.infrastructure.models import TestEntityModel
from erp.platform.concurrency import OptimisticLockError


class TestEntityRepository:
    """Persist the aggregate and enforce compare-and-increment updates."""

    async def add(self, session: AsyncSession, entity: TestEntity) -> None:
        """Stage a new aggregate in the caller-owned transaction."""
        session.add(
            TestEntityModel(
                id=entity.id,
                name=entity.name,
                status=entity.status,
                version=entity.version,
            )
        )
        await session.flush()

    async def get(self, session: AsyncSession, entity_id: UUID) -> TestEntity | None:
        """Load one aggregate without acquiring a pessimistic lock."""
        result = await session.scalars(
            select(TestEntityModel).where(TestEntityModel.id == entity_id)
        )
        model = result.one_or_none()
        return None if model is None else self._to_domain(model)

    async def mark_consumed(
        self,
        session: AsyncSession,
        *,
        entity_id: UUID,
        expected_version: int,
        consumed_at: datetime,
    ) -> TestEntity:
        """Update only the expected version and increment it atomically."""
        result = await session.scalars(
            update(TestEntityModel)
            .where(
                TestEntityModel.id == entity_id,
                TestEntityModel.version == expected_version,
                TestEntityModel.status == TestEntityStatus.CREATED,
            )
            .values(
                status=TestEntityStatus.CONSUMED,
                version=expected_version + 1,
                consumed_at=consumed_at,
            )
            .returning(TestEntityModel)
        )
        model = result.one_or_none()
        if model is None:
            raise OptimisticLockError(expected_version=expected_version)
        return self._to_domain(model)

    @staticmethod
    def _to_domain(model: TestEntityModel) -> TestEntity:
        return TestEntity(
            id=model.id,
            name=model.name,
            status=TestEntityStatus(model.status),
            version=model.version,
        )


__all__ = ["TestEntityRepository"]
