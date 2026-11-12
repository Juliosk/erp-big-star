"""M12 payment-request repository integration against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from erp.modules.finance.domain import (
    InvalidPaymentRequestError,
    PaymentApprovalAuthority,
    PaymentRequest,
    PaymentRequestItem,
    PaymentRequestStatus,
    TreasuryConflictError,
    TreasuryScopeError,
    TreasuryVersionConflictError,
)
from erp.modules.finance.infrastructure import (
    PaymentRequestItemModel,
    PaymentRequestModel,
    PaymentRequestRepository,
)
from tests.integration.test_treasury_repository import TreasuryFixture, treasury_fixture

pytestmark = pytest.mark.integration


def _request(fixture: TreasuryFixture, **changes: object) -> PaymentRequest:
    source = fixture.batch.items[0]
    values: dict[str, object] = {
        "id": uuid4(),
        "company_id": source.company_id,
        "code": f"PAYREQ-{uuid4().hex[:10].upper()}",
        "treasury_account_id": fixture.batch.treasury_account_id,
        "requested_by": fixture.batch_creator,
        "requested_at": datetime(2026, 11, 11, 12, tzinfo=UTC),
        "scheduled_on": date(2026, 12, 9),
        "purpose": "Pagamento de obrigação aprovada",
        "items": (
            PaymentRequestItem(
                id=uuid4(),
                company_id=source.company_id,
                payable_id=source.payable_id,
                installment_id=source.installment_id,
                supplier_id=source.supplier_id,
                matching_session_id=source.matching_session_id,
                amount=source.amount,
                currency=source.currency,
                due_date=source.due_date,
                beneficiary=source.beneficiary,
            ),
        ),
    }
    values.update(changes)
    return PaymentRequest(**values)  # type: ignore[arg-type]


@asynccontextmanager
async def payment_request_fixture() -> AsyncIterator[tuple[TreasuryFixture, PaymentRequest]]:
    async with treasury_fixture() as fixture:
        request = _request(fixture)
        try:
            yield fixture, request
        finally:
            data = fixture.matching.data
            async with data.database.session() as session, session.begin():
                await session.execute(
                    delete(PaymentRequestItemModel).where(
                        PaymentRequestItemModel.company_id.in_(
                            (data.company_id, data.other_company_id)
                        )
                    )
                )
                await session.execute(
                    delete(PaymentRequestModel).where(
                        PaymentRequestModel.company_id.in_((data.company_id, data.other_company_id))
                    )
                )


def test_payment_request_round_trip_lifecycle_filters_and_row_lock() -> None:
    async def scenario() -> None:
        async with payment_request_fixture() as (fixture, request):
            data = fixture.matching.data
            async with data.database.session() as session, session.begin():
                repository = PaymentRequestRepository(session, company_id=data.company_id)
                await repository.add(request, actor_id=fixture.batch_creator)
                assert await repository.get(request.id) == request
                assert await repository.get_for_update(request.id) == request
                assert await repository.list(status=PaymentRequestStatus.DRAFT) == (request,)

                pending = request.submit(workflow_instance_id=uuid4())
                await repository.save(pending, actor_id=fixture.batch_creator)
                approved = pending.approve(
                    authority=PaymentApprovalAuthority(
                        fixture.batch_approver,
                        request.currency,
                        request.total_amount + Decimal("1.00"),
                    ),
                    occurred_at=request.requested_at + timedelta(minutes=1),
                )
                await repository.save(approved, actor_id=fixture.batch_approver)
                assert await repository.get(request.id) == approved

    asyncio.run(scenario())


def test_payment_request_repository_is_tenant_bound_and_translates_conflicts() -> None:
    async def scenario() -> None:
        async with payment_request_fixture() as (fixture, request):
            data = fixture.matching.data
            async with data.database.session() as session, session.begin():
                repository = PaymentRequestRepository(session, company_id=data.company_id)
                await repository.add(request, actor_id=fixture.batch_creator)
                foreign = PaymentRequestRepository(session, company_id=data.other_company_id)
                assert await foreign.get(request.id) is None
                with pytest.raises(TreasuryScopeError):
                    await foreign.add(request, actor_id=fixture.batch_creator)

                duplicate = replace(
                    request,
                    id=uuid4(),
                    items=tuple(replace(item, id=uuid4()) for item in request.items),
                )
                savepoint = await session.begin_nested()
                with pytest.raises(TreasuryConflictError):
                    await repository.add(duplicate, actor_id=fixture.batch_creator)
                await savepoint.rollback()

                pending = request.submit(workflow_instance_id=uuid4())
                await repository.save(pending, actor_id=fixture.batch_creator)
                with pytest.raises(TreasuryVersionConflictError):
                    await repository.save(
                        pending,
                        actor_id=fixture.batch_creator,
                        expected_version=1,
                    )

    asyncio.run(scenario())


def test_payment_request_repository_rejects_invalid_contract_and_snapshot_drift() -> None:
    async def scenario() -> None:
        async with payment_request_fixture() as (fixture, request):
            data = fixture.matching.data
            async with data.database.session() as session, session.begin():
                with pytest.raises(ValueError, match="company UUID"):
                    PaymentRequestRepository(session, company_id=UUID(int=0))
                repository = PaymentRequestRepository(session, company_id=data.company_id)
                with pytest.raises(TypeError, match="PaymentRequest"):
                    await repository.add(object(), actor_id=fixture.batch_creator)  # type: ignore[arg-type]
                with pytest.raises(ValueError, match="actor UUID"):
                    await repository.add(request, actor_id=UUID(int=0))
                with pytest.raises(ValueError, match="start draft"):
                    await repository.add(
                        request.submit(workflow_instance_id=uuid4()),
                        actor_id=fixture.batch_creator,
                    )
                await repository.add(request, actor_id=fixture.batch_creator)
                pending = request.submit(workflow_instance_id=uuid4())
                with pytest.raises(InvalidPaymentRequestError, match="immutable"):
                    await repository.save(
                        replace(pending, purpose="Changed"),
                        actor_id=fixture.batch_creator,
                    )
                with pytest.raises(ValueError, match="version increment"):
                    await repository.save(request, actor_id=fixture.batch_creator)
                with pytest.raises(ValueError, match="limit"):
                    await repository.list(limit=0)
                with pytest.raises(ValueError, match="offset"):
                    await repository.list(offset=-1)
                with pytest.raises(ValueError, match="official"):
                    await repository.list(status="DRAFT")  # type: ignore[arg-type]

    asyncio.run(scenario())
