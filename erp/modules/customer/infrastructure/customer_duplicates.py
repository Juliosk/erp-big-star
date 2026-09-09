"""Session-owning adapter for M14 duplicate detection and merge requests."""

from uuid import UUID

from erp.modules.customer.application.duplicates import (
    CustomerMergeRequestResult,
    RequestCustomerMerge,
)
from erp.modules.customer.domain import (
    CustomerDuplicateCandidate,
    CustomerMergeRequest,
)
from erp.modules.customer.infrastructure.duplicate_repository import CustomerDuplicateRepository
from erp.modules.customer.infrastructure.merge_effects import CustomerMergeEffects
from erp.platform.database import Database


class PostgresCustomerDuplicates:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def detect(
        self, company_id: UUID, customer_id: UUID, actor_id: UUID
    ) -> tuple[CustomerDuplicateCandidate, ...]:
        async with self._database.session() as session, session.begin():
            return await CustomerDuplicateRepository(session, company_id=company_id).detect(
                customer_id, actor_id=actor_id
            )

    async def request_merge(
        self, command: RequestCustomerMerge, actor_id: UUID
    ) -> CustomerMergeRequestResult:
        async with self._database.session() as session, session.begin():
            repository = CustomerDuplicateRepository(session, company_id=command.company_id)
            merge_request = await repository.create_merge_request(
                CustomerMergeRequest.request(
                    company_id=command.company_id,
                    source_customer_id=command.source_customer_id,
                    candidate_customer_id=command.candidate_customer_id,
                    surviving_customer_id=command.surviving_customer_id,
                    reason=command.reason,
                ),
                actor_id=actor_id,
            )
            return await CustomerMergeEffects().record_request(
                session, merge_request, actor_id=actor_id, metadata=command.metadata
            )


__all__ = ["PostgresCustomerDuplicates"]
