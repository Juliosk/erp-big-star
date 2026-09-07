"""PostgreSQL integration proof for atomic optimistic version checks."""

import asyncio
from datetime import UTC, datetime

import pytest

from erp.modules.platform_test.domain import TestEntity as Entity
from erp.modules.platform_test.infrastructure import TestEntityRepository as EntityRepository
from erp.platform.concurrency import OptimisticLockError
from erp.platform.config import get_settings
from erp.platform.database import Database


@pytest.mark.integration
def test_stale_version_is_rejected_without_overwriting_newer_state() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        repository = EntityRepository()
        entity = Entity.create("optimistic")
        try:
            async with database.session() as session, session.begin():
                await repository.add(session, entity)
            async with database.session() as session, session.begin():
                updated = await repository.mark_consumed(
                    session,
                    entity_id=entity.id,
                    expected_version=1,
                    consumed_at=datetime.now(UTC),
                )

            async def stale_update() -> None:
                async with database.session() as session, session.begin():
                    await repository.mark_consumed(
                        session,
                        entity_id=entity.id,
                        expected_version=1,
                        consumed_at=datetime.now(UTC),
                    )

            with pytest.raises(OptimisticLockError) as captured:
                await stale_update()
            async with database.session() as session:
                stored = await repository.get(session, entity.id)

            assert updated.version == 2
            assert captured.value.code == "VERSION_CONFLICT"
            assert stored is not None
            assert stored.version == 2
        finally:
            await database.dispose()

    asyncio.run(scenario())
