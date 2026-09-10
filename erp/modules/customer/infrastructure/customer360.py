"""PostgreSQL Customer 360 adapter with explicit M14 tenant predicates."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.customer.application.customer360 import (
    Customer360Snapshot,
    CustomerDuplicateSummary,
    CustomerGroupSummary,
    CustomerMergeRequestSummary,
    CustomerMergeStatus,
)
from erp.modules.customer.infrastructure.contact_address_repository import (
    CustomerContactAddressRepository,
)
from erp.modules.customer.infrastructure.customer_repository import CustomerRepository
from erp.modules.customer.infrastructure.duplicate_model import (
    CustomerDuplicateCandidateModel,
    CustomerMergeRequestModel,
)
from erp.modules.customer.infrastructure.group_model import (
    CustomerGroupMemberModel,
    CustomerGroupModel,
)
from erp.platform.database import Database


class PostgresCustomer360:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def get(self, company_id: UUID, customer_id: UUID) -> Customer360Snapshot | None:
        async with self._database.session() as session:
            customer = await CustomerRepository(session, company_id=company_id).get(customer_id)
            if customer is None:
                return None
            contact_repository = CustomerContactAddressRepository(session, company_id=company_id)
            contacts = await contact_repository.list_contacts(customer_id)
            addresses = await contact_repository.list_addresses(customer_id)
            groups = await _groups(session, company_id=company_id, customer_id=customer_id)
            merge_status = await _merge_status(
                session, company_id=company_id, customer_id=customer_id
            )
            return Customer360Snapshot(
                customer=customer,
                contacts=contacts,
                addresses=addresses,
                groups=groups,
                merge_status=merge_status,
            )


async def _groups(
    session: AsyncSession, *, company_id: UUID, customer_id: UUID
) -> tuple[CustomerGroupSummary, ...]:
    result = await session.execute(
        select(CustomerGroupModel)
        .join(
            CustomerGroupMemberModel,
            CustomerGroupMemberModel.customer_group_id == CustomerGroupModel.id,
        )
        .where(
            CustomerGroupMemberModel.company_id == company_id,
            CustomerGroupMemberModel.customer_id == customer_id,
            CustomerGroupModel.company_id == company_id,
        )
        .order_by(CustomerGroupModel.name, CustomerGroupModel.id)
        .execution_options(populate_existing=True)
    )
    return tuple(
        CustomerGroupSummary(
            id=model.id,
            code=model.code,
            name=model.name,
            active=model.active,
        )
        for model in result.scalars()
    )


async def _merge_status(
    session: AsyncSession, *, company_id: UUID, customer_id: UUID
) -> CustomerMergeStatus:
    candidate_rows = await session.scalars(
        select(CustomerDuplicateCandidateModel)
        .where(
            CustomerDuplicateCandidateModel.company_id == company_id,
            or_(
                CustomerDuplicateCandidateModel.source_customer_id == customer_id,
                CustomerDuplicateCandidateModel.candidate_customer_id == customer_id,
            ),
        )
        .order_by(
            CustomerDuplicateCandidateModel.status,
            CustomerDuplicateCandidateModel.confidence.desc(),
            CustomerDuplicateCandidateModel.id,
        )
        .execution_options(populate_existing=True)
    )
    merge_rows = await session.scalars(
        select(CustomerMergeRequestModel)
        .where(
            CustomerMergeRequestModel.company_id == company_id,
            or_(
                CustomerMergeRequestModel.source_customer_id == customer_id,
                CustomerMergeRequestModel.candidate_customer_id == customer_id,
                CustomerMergeRequestModel.surviving_customer_id == customer_id,
            ),
        )
        .order_by(CustomerMergeRequestModel.id)
        .execution_options(populate_existing=True)
    )
    return CustomerMergeStatus(
        duplicate_candidates=tuple(
            CustomerDuplicateSummary(
                id=row.id,
                source_customer_id=row.source_customer_id,
                candidate_customer_id=row.candidate_customer_id,
                confidence=row.confidence,
                reason_codes=tuple(row.reason_codes),
                status=row.status,
            )
            for row in candidate_rows
        ),
        pending_merge_requests=tuple(
            CustomerMergeRequestSummary(
                id=row.id,
                source_customer_id=row.source_customer_id,
                candidate_customer_id=row.candidate_customer_id,
                surviving_customer_id=row.surviving_customer_id,
                status=row.status,
                version=row.version,
            )
            for row in merge_rows
        ),
    )


__all__ = ["PostgresCustomer360"]
