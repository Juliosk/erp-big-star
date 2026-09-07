"""Transactional PostgreSQL stages for the Sprint 1 golden flow."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.platform_test.application import (
    CreateTestEntityCommand,
    TestEntityCreation,
    TestEntityPersistence,
    TestEntityProcessing,
)
from erp.modules.platform_test.domain import TestEntity
from erp.modules.platform_test.infrastructure.repository import TestEntityRepository
from erp.platform.audit import AuditEvent, AuditEventModel, AuditService
from erp.platform.database import Database
from erp.platform.idempotency import IdempotencyDecision, IdempotencyService
from erp.platform.inbox import InboxService
from erp.platform.messaging import MessageEnvelope, MessageKind, build_routing_key
from erp.platform.outbox import OutboxService

TEST_ENTITY_ROUTING_KEY = build_routing_key(
    domain="platform",
    aggregate="test-entity",
    action="created",
    version=1,
)
TEST_ENTITY_CONSUMER = "platform.test-entity-projector.v1"


class PostgresTestEntityPersistence(TestEntityPersistence):
    """Keep each local effect and its platform records in one transaction."""

    def __init__(
        self,
        database: Database,
        *,
        idempotency_ttl_seconds: int,
        repository: TestEntityRepository | None = None,
        audit: AuditService | None = None,
        outbox: OutboxService | None = None,
        inbox: InboxService | None = None,
    ) -> None:
        self._database = database
        self._repository = repository or TestEntityRepository()
        self._audit = audit or AuditService()
        self._outbox = outbox or OutboxService()
        self._inbox = inbox or InboxService()
        self._idempotency = IdempotencyService(ttl_seconds=idempotency_ttl_seconds)

    async def create(self, command: CreateTestEntityCommand) -> TestEntityCreation:
        """Atomically claim the request and write entity, audit and Outbox."""
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope="platform-test",
                operation="create-test-entity",
                key=command.idempotency_key,
                payload={"name": command.name},
            )
            if decision.replayed:
                return TestEntityCreation(
                    entity_id=None,
                    event_id=None,
                    entity_version=None,
                    audit_event_id=None,
                    idempotency_record_id=decision.record_id,
                    replayed_response=decision.response_body,
                )

            entity = TestEntity.create(command.name)
            await self._repository.add(session, entity)
            envelope = MessageEnvelope.new(
                message_kind=MessageKind.DOMAIN_EVENT,
                message_type="TestEntityCreated",
                event_version=1,
                producer_module="platform",
                producer_domain="platform",
                aggregate_type="test_entity",
                aggregate_id=entity.id,
                aggregate_version=entity.version,
                company_id=None,
                branch_id=None,
                correlation_id=command.correlation_id,
                causation_id=None,
                request_id=command.request_id,
                payload={"entity_id": str(entity.id), "name": entity.name},
            )
            audit_event_id = await self._audit.record(
                session,
                AuditEvent(
                    actor_user_id=None,
                    company_id=None,
                    branch_id=None,
                    module="platform",
                    entity_type="test_entity",
                    entity_id=entity.id,
                    operation="CREATE",
                    request_id=command.request_id,
                    correlation_id=command.correlation_id,
                    after_snapshot={
                        "id": str(entity.id),
                        "name": entity.name,
                        "status": entity.status,
                        "version": entity.version,
                    },
                    source_ip=command.source_ip,
                ),
            )
            await self._outbox.enqueue(
                session,
                envelope,
                headers={"routing_key": TEST_ENTITY_ROUTING_KEY},
            )
            return TestEntityCreation(
                entity_id=entity.id,
                event_id=envelope.message_id,
                entity_version=entity.version,
                audit_event_id=audit_event_id,
                idempotency_record_id=decision.record_id,
            )

    async def consume(self, envelope: MessageEnvelope) -> TestEntityProcessing:
        """Atomically record Inbox, increment entity version and append audit."""
        processed_entity: TestEntity | None = None
        audit_event_id: UUID | None = None

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            nonlocal processed_entity, audit_event_id
            expected_version = message.aggregate_version
            if expected_version is None:
                raise ValueError("Test entity event requires aggregate_version.")
            processed_entity = await self._repository.mark_consumed(
                session,
                entity_id=message.aggregate_id,
                expected_version=expected_version,
                consumed_at=datetime.now(UTC),
            )
            audit_event_id = await self._audit.record(
                session,
                AuditEvent(
                    actor_user_id=None,
                    company_id=message.company_id,
                    branch_id=message.branch_id,
                    module="platform",
                    entity_type=message.aggregate_type,
                    entity_id=message.aggregate_id,
                    operation="CONSUME",
                    request_id=message.request_id,
                    correlation_id=message.correlation_id,
                    before_snapshot={
                        "status": "CREATED",
                        "version": expected_version,
                    },
                    after_snapshot={
                        "status": processed_entity.status,
                        "version": processed_entity.version,
                    },
                ),
            )

        async with self._database.session() as session, session.begin():
            inbox_result = await self._inbox.process(
                session,
                consumer_name=TEST_ENTITY_CONSUMER,
                envelope=envelope,
                effect=effect,
            )
            if inbox_result.duplicate:
                processed_entity = await self._repository.get(session, envelope.aggregate_id)
                audit_event_id = await self._consumer_audit_id(session, envelope)

        if processed_entity is None or audit_event_id is None:
            raise RuntimeError("Consumer transaction did not produce a durable result.")
        return TestEntityProcessing(
            entity_id=processed_entity.id,
            name=processed_entity.name,
            status=processed_entity.status,
            version=processed_entity.version,
            audit_event_id=audit_event_id,
            duplicate=inbox_result.duplicate,
        )

    async def complete_idempotency(
        self,
        *,
        record_id: UUID,
        response_body: dict[str, object],
    ) -> None:
        """Commit the exact response before acknowledging its broker delivery."""
        async with self._database.session() as session, session.begin():
            await self._idempotency.complete(
                session,
                IdempotencyDecision(record_id=record_id, replayed=False),
                response_status=201,
                response_body=response_body,
            )

    async def _consumer_audit_id(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
    ) -> UUID:
        result = await session.scalars(
            select(AuditEventModel.id)
            .where(
                AuditEventModel.entity_id == envelope.aggregate_id,
                AuditEventModel.operation == "CONSUME",
            )
            .order_by(AuditEventModel.occurred_at.desc())
            .limit(1)
        )
        return result.one()


__all__ = [
    "TEST_ENTITY_CONSUMER",
    "TEST_ENTITY_ROUTING_KEY",
    "PostgresTestEntityPersistence",
]
