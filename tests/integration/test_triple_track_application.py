"""Commit 219 application orchestration against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import (
    PAYMENT_REQUEST_APPROVED,
    PAYMENT_REQUEST_SUBMITTED,
    ChangePaymentRequest,
    PaymentRequestApplicationService,
)
from erp.modules.finance.domain import (
    InvalidPaymentRequestError,
    PaymentApprovalAuthority,
    PaymentRequestStatus,
    TreasurySodViolationError,
)
from erp.modules.finance.infrastructure import (
    PaymentRequestModel,
    PaymentRequestRepository,
    PostgresPaymentRequestEffects,
)
from erp.modules.fiscal.application import (
    TAX_RULE_ACTIVATED,
    ChangeTaxRule,
    TaxRuleApplicationService,
)
from erp.modules.fiscal.domain import TaxRuleSodViolationError, TaxRuleStatus
from erp.modules.fiscal.infrastructure import (
    PostgresTaxRuleEffects,
    TaxRuleModel,
    TaxRuleRepository,
)
from erp.modules.procurement.application import (
    REQUEST_FOR_QUOTATION_AWARDED,
    REQUEST_FOR_QUOTATION_CLOSED,
    REQUEST_FOR_QUOTATION_OPENED,
    SUPPLIER_QUOTE_RECORDED,
    ChangeRequestForQuotation,
    RequestForQuotationApplicationService,
)
from erp.modules.procurement.domain import (
    RequestForQuotationSodViolationError,
    RequestForQuotationStatus,
)
from erp.modules.procurement.infrastructure import (
    PostgresRequestForQuotationEffects,
    RequestForQuotationModel,
    RequestForQuotationRepository,
)
from erp.platform.audit import AuditEventModel
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.messaging import MessageEnvelope
from erp.platform.outbox import OutboxEventModel
from tests.integration.test_payment_request_repository import payment_request_fixture
from tests.integration.test_rfq_repository import _quote, rfq_fixture
from tests.integration.test_tax_rule_repository import tax_rule_fixture

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class _AuthorityMatrix:
    company_id: UUID
    limits: dict[UUID, Decimal]

    async def authority_for(
        self,
        *,
        company_id: UUID,
        actor_id: UUID,
        currency: str,
    ) -> PaymentApprovalAuthority | None:
        if company_id != self.company_id or actor_id not in self.limits:
            return None
        return PaymentApprovalAuthority(actor_id, currency, self.limits[actor_id])


class _FailingOutbox:
    async def enqueue(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
        *,
        headers: dict[str, Any] | None = None,
    ) -> UUID:
        del session, envelope, headers
        raise RuntimeError("forced outbox failure")


@asynccontextmanager
async def _effect_cleanup(
    database: Database,
    aggregate_ids: tuple[UUID, ...],
) -> AsyncIterator[None]:
    try:
        yield
    finally:
        async with database.session() as session, session.begin():
            await session.execute(
                delete(OutboxEventModel).where(OutboxEventModel.aggregate_id.in_(aggregate_ids))
            )
            await session.execute(
                delete(AuditEventModel).where(AuditEventModel.entity_id.in_(aggregate_ids))
            )


async def _event_types(session: AsyncSession, aggregate_id: UUID) -> tuple[str, ...]:
    values = await session.scalars(
        select(OutboxEventModel.event_type)
        .where(OutboxEventModel.aggregate_id == aggregate_id)
        .order_by(OutboxEventModel.occurred_at, OutboxEventModel.event_type)
    )
    return tuple(values)


async def _audit_operations(session: AsyncSession, entity_id: UUID) -> tuple[str, ...]:
    values = await session.scalars(
        select(AuditEventModel.operation)
        .where(AuditEventModel.entity_id == entity_id)
        .order_by(AuditEventModel.occurred_at, AuditEventModel.operation)
    )
    return tuple(values)


def test_tax_rule_activation_enforces_sod_tenant_and_atomic_effects() -> None:
    async def scenario() -> None:
        async with tax_rule_fixture() as (data, rule), _effect_cleanup(data.database, (rule.id,)):
            async with data.database.session() as session, session.begin():
                repository = TaxRuleRepository(session, company_id=data.company_id)
                await repository.add(rule, actor_id=data.actor_id)

            occurred_at = datetime(2026, 11, 12, 10, tzinfo=UTC)
            async with data.database.session() as session, session.begin():
                repository = TaxRuleRepository(session, company_id=data.company_id)
                service = TaxRuleApplicationService(
                    repository,
                    PostgresTaxRuleEffects(session),
                )
                command = ChangeTaxRule(
                    data.company_id,
                    rule.id,
                    rule.version,
                    occurred_at,
                )
                with pytest.raises(TaxRuleSodViolationError):
                    await service.activate(command, actor_id=rule.created_by)

                foreign = TaxRuleApplicationService(
                    TaxRuleRepository(session, company_id=data.other_company_id),
                    PostgresTaxRuleEffects(session),
                )
                with pytest.raises(ApplicationError) as not_found:
                    await foreign.activate(command, actor_id=data.actor_id)
                assert not_found.value.code == "RESOURCE_NOT_FOUND"

                result = await service.activate(command, actor_id=data.actor_id)
                assert result.rule.status is TaxRuleStatus.ACTIVE

            async with data.database.session() as session:
                persisted = await TaxRuleRepository(session, company_id=data.company_id).get(
                    rule.id
                )
                assert persisted == result.rule
                assert await _event_types(session, rule.id) == (TAX_RULE_ACTIVATED,)
                assert await _audit_operations(session, rule.id) == (TAX_RULE_ACTIVATED,)
                assert await session.get(AuditEventModel, result.audit_id) is not None
                assert (
                    await session.scalar(
                        select(OutboxEventModel).where(OutboxEventModel.event_id == result.event_id)
                    )
                    is not None
                )

    asyncio.run(scenario())


def test_rfq_complete_lifecycle_enforces_sod_and_publishes_every_transition() -> None:
    async def scenario() -> None:
        async with (
            rfq_fixture() as (data, rfq, supplier_id),
            _effect_cleanup(data.database, (rfq.id,)),
        ):
            async with data.database.session() as session, session.begin():
                repository = RequestForQuotationRepository(session, company_id=data.company_id)
                await repository.add(rfq, actor_id=data.actor_id)
                service = RequestForQuotationApplicationService(
                    repository,
                    PostgresRequestForQuotationEffects(session),
                )
                opened = await service.open(
                    ChangeRequestForQuotation(data.company_id, rfq.id, 1),
                    actor_id=data.actor_id,
                    occurred_at=datetime(2026, 11, 11, 9, tzinfo=UTC),
                )
                quoted = await service.record_quote(
                    ChangeRequestForQuotation(data.company_id, rfq.id, 2),
                    actor_id=supplier_id,
                    quote=_quote(rfq, supplier_id),
                )
                closed = await service.close(
                    ChangeRequestForQuotation(data.company_id, rfq.id, 3),
                    actor_id=data.actor_id,
                    occurred_at=datetime(2026, 11, 13, 9, tzinfo=UTC),
                )
                award_command = ChangeRequestForQuotation(data.company_id, rfq.id, 4)
                with pytest.raises(RequestForQuotationSodViolationError):
                    await service.award(
                        award_command,
                        actor_id=rfq.created_by,
                        quote_id=quoted.rfq.supplier_quotes[0].id,
                        occurred_at=datetime(2026, 11, 14, 9, tzinfo=UTC),
                    )
                adjudicator = uuid4()
                awarded = await service.award(
                    award_command,
                    actor_id=adjudicator,
                    quote_id=quoted.rfq.supplier_quotes[0].id,
                    occurred_at=datetime(2026, 11, 14, 9, tzinfo=UTC),
                )
                assert opened.rfq.status is RequestForQuotationStatus.OPEN
                assert closed.rfq.status is RequestForQuotationStatus.CLOSED
                assert awarded.rfq.status is RequestForQuotationStatus.AWARDED
                assert awarded.rfq.award is not None
                assert awarded.rfq.award.awarded_by == adjudicator

            expected = (
                REQUEST_FOR_QUOTATION_OPENED,
                SUPPLIER_QUOTE_RECORDED,
                REQUEST_FOR_QUOTATION_CLOSED,
                REQUEST_FOR_QUOTATION_AWARDED,
            )
            async with data.database.session() as session:
                persisted = await RequestForQuotationRepository(
                    session, company_id=data.company_id
                ).get(rfq.id)
                assert persisted == awarded.rfq
                assert set(await _event_types(session, rfq.id)) == set(expected)
                assert set(await _audit_operations(session, rfq.id)) == set(expected)

    asyncio.run(scenario())


def test_payment_request_uses_trusted_multi_tier_authority_and_sod() -> None:
    async def scenario() -> None:
        async with (
            payment_request_fixture() as (fixture, request),
            _effect_cleanup(fixture.matching.data.database, (request.id,)),
        ):
            data = fixture.matching.data
            low_actor = uuid4()
            high_actor = fixture.batch_approver
            matrix = _AuthorityMatrix(
                data.company_id,
                {
                    low_actor: request.total_amount - Decimal("0.01"),
                    high_actor: request.total_amount + Decimal("100.00"),
                    request.requested_by: request.total_amount + Decimal("100.00"),
                },
            )
            async with data.database.session() as session, session.begin():
                repository = PaymentRequestRepository(session, company_id=data.company_id)
                await repository.add(request, actor_id=request.requested_by)
                service = PaymentRequestApplicationService(
                    repository,
                    matrix,
                    PostgresPaymentRequestEffects(session),
                )
                foreign = PaymentRequestApplicationService(
                    PaymentRequestRepository(session, company_id=data.other_company_id),
                    matrix,
                    PostgresPaymentRequestEffects(session),
                )
                with pytest.raises(ApplicationError) as not_found:
                    await foreign.submit(
                        ChangePaymentRequest(data.company_id, request.id, 1),
                        actor_id=request.requested_by,
                        workflow_instance_id=uuid4(),
                    )
                assert not_found.value.code == "RESOURCE_NOT_FOUND"

                submitted = await service.submit(
                    ChangePaymentRequest(data.company_id, request.id, 1),
                    actor_id=request.requested_by,
                    workflow_instance_id=uuid4(),
                )
                decision_at = request.requested_at + timedelta(minutes=5)
                approve_command = ChangePaymentRequest(data.company_id, request.id, 2)
                with pytest.raises(InvalidPaymentRequestError, match="does not cover"):
                    await service.approve(
                        approve_command,
                        actor_id=low_actor,
                        occurred_at=decision_at,
                    )
                with pytest.raises(TreasurySodViolationError):
                    await service.approve(
                        approve_command,
                        actor_id=request.requested_by,
                        occurred_at=decision_at,
                    )
                approved = await service.approve(
                    approve_command,
                    actor_id=high_actor,
                    occurred_at=decision_at,
                )
                assert submitted.request.status is PaymentRequestStatus.PENDING_APPROVAL
                assert approved.request.status is PaymentRequestStatus.APPROVED
                assert approved.request.approved_by == high_actor

            async with data.database.session() as session:
                persisted = await PaymentRequestRepository(session, company_id=data.company_id).get(
                    request.id
                )
                assert persisted == approved.request
                expected = (PAYMENT_REQUEST_SUBMITTED, PAYMENT_REQUEST_APPROVED)
                assert set(await _event_types(session, request.id)) == set(expected)
                assert set(await _audit_operations(session, request.id)) == set(expected)

    asyncio.run(scenario())


def test_outbox_failure_rolls_back_all_triple_track_mutations_and_audits() -> None:
    async def scenario() -> None:
        await _assert_tax_rule_rollback()
        await _assert_rfq_rollback()
        await _assert_payment_request_rollback()

    asyncio.run(scenario())


async def _assert_tax_rule_rollback() -> None:
    async with tax_rule_fixture() as (data, rule), _effect_cleanup(data.database, (rule.id,)):
        async with data.database.session() as session, session.begin():
            await TaxRuleRepository(session, company_id=data.company_id).add(
                rule, actor_id=data.actor_id
            )
        with pytest.raises(RuntimeError, match="outbox"):
            async with data.database.session() as session, session.begin():
                await TaxRuleApplicationService(
                    TaxRuleRepository(session, company_id=data.company_id),
                    PostgresTaxRuleEffects(session, outbox=_FailingOutbox()),
                ).activate(
                    ChangeTaxRule(
                        data.company_id,
                        rule.id,
                        1,
                        datetime(2026, 11, 12, 10, tzinfo=UTC),
                    ),
                    actor_id=data.actor_id,
                )
        await _assert_rolled_back(data.database, rule.id, TaxRuleStatus.DRAFT.value)


async def _assert_rfq_rollback() -> None:
    async with rfq_fixture() as (data, rfq, _), _effect_cleanup(data.database, (rfq.id,)):
        async with data.database.session() as session, session.begin():
            await RequestForQuotationRepository(session, company_id=data.company_id).add(
                rfq, actor_id=data.actor_id
            )
        with pytest.raises(RuntimeError, match="outbox"):
            async with data.database.session() as session, session.begin():
                await RequestForQuotationApplicationService(
                    RequestForQuotationRepository(session, company_id=data.company_id),
                    PostgresRequestForQuotationEffects(session, outbox=_FailingOutbox()),
                ).open(
                    ChangeRequestForQuotation(data.company_id, rfq.id, 1),
                    actor_id=data.actor_id,
                    occurred_at=datetime(2026, 11, 11, 9, tzinfo=UTC),
                )
        await _assert_rolled_back(data.database, rfq.id, RequestForQuotationStatus.DRAFT.value)


async def _assert_payment_request_rollback() -> None:
    async with (
        payment_request_fixture() as (fixture, request),
        _effect_cleanup(fixture.matching.data.database, (request.id,)),
    ):
        data = fixture.matching.data
        async with data.database.session() as session, session.begin():
            await PaymentRequestRepository(session, company_id=data.company_id).add(
                request, actor_id=request.requested_by
            )
        with pytest.raises(RuntimeError, match="outbox"):
            async with data.database.session() as session, session.begin():
                await PaymentRequestApplicationService(
                    PaymentRequestRepository(session, company_id=data.company_id),
                    _AuthorityMatrix(data.company_id, {}),
                    PostgresPaymentRequestEffects(session, outbox=_FailingOutbox()),
                ).submit(
                    ChangePaymentRequest(data.company_id, request.id, 1),
                    actor_id=request.requested_by,
                    workflow_instance_id=uuid4(),
                )
        await _assert_rolled_back(data.database, request.id, PaymentRequestStatus.DRAFT.value)


async def _assert_rolled_back(
    database: Database,
    aggregate_id: UUID,
    expected_status: str,
) -> None:
    async with database.session() as session:
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(AuditEventModel.entity_id == aggregate_id)
        )
        outbox_count = await session.scalar(
            select(func.count())
            .select_from(OutboxEventModel)
            .where(OutboxEventModel.aggregate_id == aggregate_id)
        )
        assert audit_count == 0
        assert outbox_count == 0
        statuses = (
            await session.execute(
                select(
                    # Each aggregate identity is globally unique; union-free probes
                    # keep this assertion independent from repository types.
                    func.coalesce(
                        (
                            select(TaxRuleModel.status)
                            .where(TaxRuleModel.id == aggregate_id)
                            .scalar_subquery()
                        ),
                        (
                            select(RequestForQuotationModel.status)
                            .where(RequestForQuotationModel.id == aggregate_id)
                            .scalar_subquery()
                        ),
                        (
                            select(PaymentRequestModel.status)
                            .where(PaymentRequestModel.id == aggregate_id)
                            .scalar_subquery()
                        ),
                    )
                )
            )
        ).scalar_one()
        assert statuses == expected_status
