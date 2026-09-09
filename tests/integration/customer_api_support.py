"""HTTP integration harness for M14 with real database and test-only identity."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, or_, select

from erp.apps.api.app import create_app
from erp.modules.admin.application import SecurityContext
from erp.modules.admin.domain import AuthenticatedPrincipal, AuthenticationLevel, Scope, ScopeType
from erp.modules.customer.application.permissions import CUSTOMER_READ
from erp.modules.customer.infrastructure import (
    CustomerDuplicateCandidateModel,
    CustomerGroupMemberModel,
    CustomerGroupModel,
    CustomerMergeRequestModel,
    CustomerModel,
)
from erp.platform.audit import AuditEventModel
from erp.platform.config import get_settings
from erp.platform.idempotency.models import IdempotencyRecordModel
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_customer_persistence import CustomerFixture, customer_fixture


class ResolverStub:
    context: SecurityContext | None = None

    async def resolve(self, access_token: str) -> SecurityContext | None:
        return self.context if access_token == "customer-test-token" else None


@dataclass
class CustomerApiFixture:
    client: TestClient
    data: CustomerFixture
    resolver: ResolverStub

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer customer-test-token"}

    @property
    def url(self) -> str:
        return f"/api/v1/customers?company_id={self.data.company_id}"


@contextmanager
def customer_api() -> Iterator[CustomerApiFixture]:
    resolver = ResolverStub()
    with TestClient(create_app(get_settings(), security_context_resolver=resolver)) as client:
        assert client.portal is not None
        manager = customer_fixture()
        data = client.portal.call(manager.__aenter__)
        resolver.context = SecurityContext(
            principal=AuthenticatedPrincipal(data.actor_id, uuid4(), AuthenticationLevel.LEVEL_1),
            permissions=frozenset({CUSTOMER_READ}),
            scopes=frozenset({Scope(ScopeType.COMPANY, data.company_id)}),
        )
        try:
            yield CustomerApiFixture(client, data, resolver)
        finally:

            async def cleanup_effects() -> None:
                company_ids = (data.company_id, data.other_company_id)
                async with data.database.session() as session, session.begin():
                    customer_ids = select(CustomerModel.id).where(
                        CustomerModel.company_id.in_(company_ids)
                    )
                    merge_ids = select(CustomerMergeRequestModel.id).where(
                        CustomerMergeRequestModel.company_id.in_(company_ids)
                    )
                    await session.execute(
                        delete(OutboxEventModel).where(
                            OutboxEventModel.source_module == "crm",
                            or_(
                                OutboxEventModel.aggregate_id.in_(customer_ids),
                                OutboxEventModel.aggregate_id.in_(merge_ids),
                            ),
                        )
                    )
                    await session.execute(
                        delete(AuditEventModel).where(
                            AuditEventModel.module == "crm",
                            AuditEventModel.company_id.in_(company_ids),
                        )
                    )
                    await session.execute(
                        delete(IdempotencyRecordModel).where(
                            IdempotencyRecordModel.scope.in_(
                                f"customer:{company_id}:{data.actor_id}"
                                for company_id in company_ids
                            )
                        )
                    )
                    await session.execute(
                        delete(CustomerGroupMemberModel).where(
                            CustomerGroupMemberModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(CustomerMergeRequestModel).where(
                            CustomerMergeRequestModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(CustomerDuplicateCandidateModel).where(
                            CustomerDuplicateCandidateModel.company_id.in_(company_ids)
                        )
                    )
                    await session.execute(
                        delete(CustomerGroupModel).where(
                            CustomerGroupModel.company_id.in_(company_ids)
                        )
                    )

            try:
                client.portal.call(cleanup_effects)
            finally:
                client.portal.call(manager.__aexit__, None, None, None)
