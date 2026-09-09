"""Direct M14 duplicate repository edge cases."""

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from erp.modules.customer.domain import CustomerMergeRequest
from erp.modules.customer.infrastructure.duplicate_repository import CustomerDuplicateRepository
from erp.platform.errors import ApplicationError
from tests.integration.test_customer_persistence import customer_fixture

pytestmark = pytest.mark.integration


def test_duplicate_repository_rejects_scope_actor_and_missing_customer_edges() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="company UUID"):
            CustomerDuplicateRepository(cast(Any, object()), company_id=cast(Any, "bad"))
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            repository = CustomerDuplicateRepository(session, company_id=data.company_id)
            with pytest.raises(ValueError, match="actor UUID"):
                await repository.detect(uuid4(), actor_id=cast(Any, "bad"))
            with pytest.raises(ApplicationError) as missing:
                await repository.detect(uuid4(), actor_id=data.actor_id)
            assert missing.value.code == "RESOURCE_NOT_FOUND"
            source, candidate = uuid4(), uuid4()
            request = CustomerMergeRequest.request(
                company_id=data.other_company_id,
                source_customer_id=source,
                candidate_customer_id=candidate,
                surviving_customer_id=source,
                reason="Outro escopo",
            )
            with pytest.raises(ApplicationError) as scope:
                await repository.create_merge_request(request, actor_id=data.actor_id)
            assert scope.value.code == "SCOPE_FORBIDDEN"
            object.__setattr__(request, "company_id", data.company_id)
            with pytest.raises(ValueError, match="actor UUID"):
                await repository.create_merge_request(request, actor_id=cast(Any, "bad"))

    asyncio.run(scenario())


def test_duplicate_repository_records_empty_detection_without_flush() -> None:
    async def scenario() -> None:
        async with customer_fixture() as data, data.database.session() as session, session.begin():
            customer_repository = __import__(
                "erp.modules.customer.infrastructure.customer_repository",
                fromlist=["CustomerRepository"],
            ).CustomerRepository(session, company_id=data.company_id)
            customer = data.customer(legal_name="Cliente unico")
            await customer_repository.add(customer, actor_id=data.actor_id)
            repository = CustomerDuplicateRepository(session, company_id=data.company_id)
            assert await repository.detect(customer.id, actor_id=data.actor_id) == ()

    asyncio.run(scenario())


def test_duplicate_repository_non_duplicate_integrity_errors_are_not_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReferentialIntegrityError(Exception):
        sqlstate = "23503"

    class SessionStub:
        def add(self, model: object) -> None:
            assert model is not None

        async def flush(self) -> None:
            raise IntegrityError(None, None, ReferentialIntegrityError())

        async def execute(self, statement: object) -> None:
            assert statement is not None

    async def require_customer(customer_id: object) -> None:
        assert customer_id is not None

    company_id = uuid4()
    repository = CustomerDuplicateRepository(cast(Any, SessionStub()), company_id=company_id)
    monkeypatch.setattr(repository, "_require_customer", require_customer)
    source, candidate = uuid4(), uuid4()
    request = CustomerMergeRequest.request(
        company_id=company_id,
        source_customer_id=source,
        candidate_customer_id=candidate,
        surviving_customer_id=source,
        reason="Possivel duplicidade",
    )
    with pytest.raises(IntegrityError):
        asyncio.run(repository.create_merge_request(request, actor_id=uuid4()))
