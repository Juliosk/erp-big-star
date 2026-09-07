"""PostgreSQL integration coverage for append-only audit persistence."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from erp.platform.audit import AuditEvent, AuditEventModel, AuditService
from erp.platform.config import get_settings
from erp.platform.database import Database


@pytest.mark.integration
def test_audit_event_is_persisted_with_masked_snapshot() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        entity_id = uuid4()
        request_id = uuid4()
        try:
            async with database.session() as session, session.begin():
                audit_id = await AuditService().record(
                    session,
                    AuditEvent(
                        actor_user_id=None,
                        company_id=None,
                        branch_id=None,
                        module="platform",
                        entity_type="test_entity",
                        entity_id=entity_id,
                        operation="CREATE",
                        request_id=request_id,
                        correlation_id=request_id,
                        after_snapshot={"name": "first", "password": "do-not-store"},
                    ),
                )

            async with database.session() as session:
                stored = await session.scalar(
                    select(AuditEventModel).where(AuditEventModel.id == audit_id)
                )

            assert stored is not None
            assert stored.entity_id == entity_id
            assert stored.after_snapshot == {"name": "first", "password": "***MASKED***"}
        finally:
            await database.dispose()

    asyncio.run(scenario())
