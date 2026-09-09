"""Tenant-bound duplicate detection and merge request persistence."""

from uuid import UUID

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.customer.domain import (
    Customer,
    CustomerDuplicateCandidate,
    CustomerMergeRequest,
    MergeRequestStatus,
    detect_duplicate_candidates,
)
from erp.modules.customer.infrastructure.customer_repository import CustomerRepository
from erp.modules.customer.infrastructure.duplicate_model import (
    CustomerDuplicateCandidateModel,
    CustomerMergeRequestModel,
)
from erp.platform.errors import ApplicationError


def _merge_request(model: CustomerMergeRequestModel) -> CustomerMergeRequest:
    return CustomerMergeRequest(
        id=model.id,
        company_id=model.company_id,
        source_customer_id=model.source_customer_id,
        candidate_customer_id=model.candidate_customer_id,
        surviving_customer_id=model.surviving_customer_id,
        status=MergeRequestStatus(model.status),
        reason=model.reason,
        version=model.version,
    )


class CustomerDuplicateRepository:
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def detect(
        self, customer_id: UUID, *, actor_id: UUID
    ) -> tuple[CustomerDuplicateCandidate, ...]:
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")
        customer_repository = CustomerRepository(self._session, company_id=self._company_id)
        source = await customer_repository.get(customer_id)
        if source is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Customer not found.", status_code=404
            )
        candidates = await customer_repository.list(
            limit=100, offset=0, status=None, customer_type=None
        )
        detected = detect_duplicate_candidates(source, candidates)
        await self._record_candidates(detected, actor_id=actor_id)
        return detected

    async def create_merge_request(
        self, merge_request: CustomerMergeRequest, *, actor_id: UUID
    ) -> CustomerMergeRequest:
        self._validate_merge_request(merge_request, actor_id)
        await self._require_customer(merge_request.source_customer_id)
        await self._require_customer(merge_request.candidate_customer_id)
        await self._require_customer(merge_request.surviving_customer_id)
        model = CustomerMergeRequestModel(
            id=merge_request.id,
            company_id=self._company_id,
            source_customer_id=merge_request.source_customer_id,
            candidate_customer_id=merge_request.candidate_customer_id,
            surviving_customer_id=merge_request.surviving_customer_id,
            status=merge_request.status,
            reason=merge_request.reason,
            created_by=actor_id,
            updated_by=actor_id,
            version=merge_request.version,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code="CUSTOMER_MERGE_REQUEST_CONFLICT",
                    message="A pending merge request already exists for this customer pair.",
                    status_code=409,
                ) from error
            raise
        await self._mark_candidate_requested(merge_request)
        return _merge_request(model)

    async def _record_candidates(
        self, candidates: tuple[CustomerDuplicateCandidate, ...], *, actor_id: UUID
    ) -> None:
        for candidate in candidates:
            statement = (
                insert(CustomerDuplicateCandidateModel)
                .values(
                    id=candidate.id,
                    company_id=self._company_id,
                    source_customer_id=candidate.source_customer_id,
                    candidate_customer_id=candidate.candidate_customer_id,
                    confidence=candidate.confidence,
                    reason_codes=[reason.value for reason in candidate.reason_codes],
                    status="SUGGESTED",
                    created_by=actor_id,
                )
                .on_conflict_do_nothing(
                    constraint="uq_customer_duplicate_candidate_pair",
                )
            )
            await self._session.execute(statement)
        if candidates:
            await self._session.flush()

    async def _mark_candidate_requested(self, merge_request: CustomerMergeRequest) -> None:
        await self._session.execute(
            update(CustomerDuplicateCandidateModel)
            .where(
                CustomerDuplicateCandidateModel.company_id == self._company_id,
                CustomerDuplicateCandidateModel.source_customer_id
                == merge_request.source_customer_id,
                CustomerDuplicateCandidateModel.candidate_customer_id
                == merge_request.candidate_customer_id,
            )
            .values(status="MERGE_REQUESTED")
        )

    async def _require_customer(self, customer_id: UUID) -> Customer:
        customer = await CustomerRepository(self._session, company_id=self._company_id).get(
            customer_id
        )
        if customer is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Customer not found.", status_code=404
            )
        return customer

    def _validate_merge_request(self, merge_request: CustomerMergeRequest, actor_id: UUID) -> None:
        if merge_request.company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The merge request is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")


__all__ = ["CustomerDuplicateRepository"]
