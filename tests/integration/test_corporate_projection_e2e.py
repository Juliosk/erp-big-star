"""Official M1 HTTP -> Outbox -> RabbitMQ -> Inbox -> projection flow."""

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from erp.apps.api.app import create_app
from erp.modules.admin.application import (
    ADMIN_BRANCH_CREATE,
    ADMIN_COMPANY_CREATE,
    SecurityContext,
)
from erp.modules.admin.domain import (
    AuthenticatedPrincipal,
    AuthenticationLevel,
    EconomicGroup,
    Scope,
    ScopeType,
)
from erp.modules.admin.infrastructure import (
    CorporateEventProjectionModel,
    CorporateProjectionConsumer,
    EconomicGroupRepository,
    RabbitCorporateEventTransport,
)
from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.inbox import InboxEventModel
from erp.platform.messaging import RabbitMQBroker
from erp.platform.outbox import OutboxEventModel


class ResolverStub:
    def __init__(self, context: SecurityContext) -> None:
        self.context = context

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "e2e-token" else None


def _cnpj(prefix: str, seed: int) -> str:
    base = f"{prefix}{seed:010d}"

    def digit(value: str, weights: tuple[int, ...]) -> str:
        remainder = (
            sum(int(number) * weight for number, weight in zip(value, weights, strict=True)) % 11
        )
        result = 11 - remainder
        return str(0 if result >= 10 else result)

    first = digit(base, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return base + first + digit(base + first, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))


@pytest.mark.integration
def test_corporate_created_events_are_confirmed_and_projected_exactly_once() -> None:
    settings = get_settings()
    seed = uuid4().int % 10_000_000_000
    actor_id = uuid4()
    group = EconomicGroup.create(code=f"E2E_{uuid4().hex[:8]}", name="E2E Group")

    async def seed_group() -> None:
        database = Database(settings)
        try:
            async with database.session() as session, session.begin():
                await EconomicGroupRepository().add(session, group, actor_id=actor_id)
        finally:
            await database.dispose()

    asyncio.run(seed_group())
    resolver = ResolverStub(
        SecurityContext(
            principal=AuthenticatedPrincipal(actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset({ADMIN_COMPANY_CREATE, ADMIN_BRANCH_CREATE}),
            scopes=frozenset({Scope(ScopeType.GROUP, group.id)}),
        )
    )
    headers = {"Authorization": "Bearer e2e-token"}
    with TestClient(create_app(settings, security_context_resolver=resolver)) as client:
        company_response = client.post(
            "/api/v1/admin/companies",
            json={
                "group_id": str(group.id),
                "code": f"EC_{uuid4().hex[:8]}",
                "legal_name": "Projected Company",
                "trade_name": None,
                "tax_id": _cnpj("31", seed),
                "timezone": "America/Sao_Paulo",
            },
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )
        branch_response = client.post(
            "/api/v1/admin/branches",
            json={
                "company_id": company_response.json()["company"]["id"],
                "code": f"EB_{uuid4().hex[:8]}",
                "name": "Projected Branch",
                "tax_id": _cnpj("32", seed),
                "timezone": "America/Sao_Paulo",
            },
            headers={**headers, "Idempotency-Key": str(uuid4())},
        )

    assert company_response.status_code == branch_response.status_code == 201
    event_ids = {
        "CompanyCreated": UUID(company_response.json()["event_id"]),
        "BranchCreated": UUID(branch_response.json()["event_id"]),
    }

    async def publish_consume_and_assert() -> None:
        database = Database(settings)
        broker = RabbitMQBroker(settings)
        transport = RabbitCorporateEventTransport(database, broker)
        consumer = CorporateProjectionConsumer(database)
        try:
            await transport.purge()
            for message_type, event_id in event_ids.items():
                await transport.publish(event_id)
                delivery = await transport.receive(message_type, timeout_seconds=2.0)
                assert delivery is not None
                first = await consumer.consume(delivery.envelope)
                duplicate = await consumer.consume(delivery.envelope)
                assert first.processed is True
                assert duplicate.duplicate is True
                await delivery.ack()

            async with database.session() as session:
                projections = (
                    await session.scalars(
                        select(CorporateEventProjectionModel).where(
                            CorporateEventProjectionModel.event_id.in_(set(event_ids.values()))
                        )
                    )
                ).all()
                inbox = (
                    await session.scalars(
                        select(InboxEventModel).where(
                            InboxEventModel.event_id.in_(set(event_ids.values()))
                        )
                    )
                ).all()
                outbox = (
                    await session.scalars(
                        select(OutboxEventModel).where(
                            OutboxEventModel.event_id.in_(set(event_ids.values()))
                        )
                    )
                ).all()
            assert {item.message_type for item in projections} == set(event_ids)
            assert len(inbox) == 2
            assert all(item.processed_at is not None for item in inbox)
            assert all(item.published_at is not None for item in outbox)
            assert all(item.publish_attempts == 1 for item in outbox)
            await transport.purge()
        finally:
            await broker.close()
            await database.dispose()

    asyncio.run(publish_consume_and_assert())
