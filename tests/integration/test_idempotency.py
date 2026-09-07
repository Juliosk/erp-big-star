"""PostgreSQL integration coverage for command idempotency semantics."""

import asyncio
from uuid import uuid4

import pytest

from erp.platform.config import get_settings
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyService


@pytest.mark.integration
def test_same_key_and_payload_replays_original_result() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        service = IdempotencyService(ttl_seconds=3600)
        key = str(uuid4())
        payload = {"name": "replay"}
        try:
            async with database.session() as session, session.begin():
                first = await service.begin(
                    session,
                    scope="integration",
                    operation="create-test-entity",
                    key=key,
                    payload=payload,
                )
                await service.complete(
                    session,
                    first,
                    response_status=201,
                    response_body={"id": "entity-1", "status": "CREATED"},
                )
            async with database.session() as session, session.begin():
                replay = await service.begin(
                    session,
                    scope="integration",
                    operation="create-test-entity",
                    key=key,
                    payload=payload,
                )

            assert first.replayed is False
            assert replay.replayed is True
            assert replay.response_status == 201
            assert replay.response_body == {"id": "entity-1", "status": "CREATED"}
        finally:
            await database.dispose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_same_key_with_different_payload_returns_stable_conflict() -> None:
    async def scenario() -> None:
        database = Database(get_settings())
        service = IdempotencyService(ttl_seconds=3600)
        key = str(uuid4())
        try:
            async with database.session() as session, session.begin():
                decision = await service.begin(
                    session,
                    scope="integration",
                    operation="create-test-entity",
                    key=key,
                    payload={"name": "first"},
                )
                await service.complete(
                    session,
                    decision,
                    response_status=201,
                    response_body={"id": "entity-2"},
                )

            async def conflicting_request() -> None:
                async with database.session() as session, session.begin():
                    await service.begin(
                        session,
                        scope="integration",
                        operation="create-test-entity",
                        key=key,
                        payload={"name": "different"},
                    )

            with pytest.raises(ApplicationError) as captured:
                await conflicting_request()

            assert captured.value.status_code == 409
            assert captured.value.code == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"
        finally:
            await database.dispose()

    asyncio.run(scenario())


@pytest.mark.integration
def test_rolled_back_claim_can_be_retried_as_new_work() -> None:
    class TransactionFailure(Exception):
        pass

    async def scenario() -> None:
        database = Database(get_settings())
        service = IdempotencyService(ttl_seconds=3600)
        key = str(uuid4())

        async def claim_then_fail() -> None:
            async with database.session() as session, session.begin():
                await service.begin(
                    session,
                    scope="integration",
                    operation="rollback-command",
                    key=key,
                    payload={"name": "retryable"},
                )
                raise TransactionFailure

        try:
            with pytest.raises(TransactionFailure):
                await claim_then_fail()
            async with database.session() as session, session.begin():
                retry = await service.begin(
                    session,
                    scope="integration",
                    operation="rollback-command",
                    key=key,
                    payload={"name": "retryable"},
                )

            assert retry.replayed is False
        finally:
            await database.dispose()

    asyncio.run(scenario())
