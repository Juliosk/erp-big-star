"""Atomic M6/M22 composition for governed matching exceptions."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.admin.contracts import SecurityContext
from erp.modules.fiscal.infrastructure import InboundFiscalDocumentModel
from erp.modules.procurement.application import (
    DecideMatchingOverride,
    MatchingGovernanceAuthorization,
    MatchingGovernanceResult,
    MatchingGovernanceStore,
    MatchingOverrideDecision,
    MatchingWorkflowStepView,
    MatchingWorkflowView,
    ProcurementAuthorization,
    ProcurementCommandMetadata,
    RequestMatchingOverride,
)
from erp.modules.procurement.application.matching_governance import (
    normalize_override_reason,
    validate_governance_version,
)
from erp.modules.procurement.domain import (
    MatchStatus,
    ThreeWayMatchSession,
    ThreeWayMatchSessionStatus,
)
from erp.modules.procurement.infrastructure import (
    MatchingSessionModel,
    PurchaseOrderModel,
    ThreeWayMatchRepository,
)
from erp.modules.workflow.application import WorkflowAuthorization
from erp.modules.workflow.application.decisions import (
    CommandMetadata,
    DecideWorkflowInstance,
)
from erp.modules.workflow.domain import (
    ApprovalDecisionKind,
    ApprovalMode,
    WorkflowInstance,
    WorkflowInstanceStatus,
    WorkflowStepDefinition,
    WorkflowStepInstance,
)
from erp.modules.workflow.infrastructure import (
    WorkflowInstanceModel,
    WorkflowRepository,
    apply_workflow_decision,
)
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail
from erp.platform.idempotency import IdempotencyDecision, IdempotencyService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService

MATCHING_OVERRIDE_REQUESTED = "MatchingOverrideRequested"
MATCHING_OVERRIDE_APPROVED = "MatchingOverrideApproved"
MATCHING_OVERRIDE_REJECTED = "MatchingOverrideRejected"
_SOURCE_MODULE = "PROCUREMENT"
_SOURCE_TYPE = "MATCHING_OVERRIDE"
_ELIGIBLE_REPORTS = {MatchStatus.TOLERANCE_EXCEEDED, MatchStatus.PRICE_MISMATCH}


class MatchingWorkflowAuthorization(MatchingGovernanceAuthorization):
    """Compose the M6 and M22 permission policies without leaking either inward."""

    def __init__(
        self,
        procurement: ProcurementAuthorization,
        workflow: WorkflowAuthorization,
    ) -> None:
        self._procurement = procurement
        self._workflow = workflow

    async def require_request(self, context: SecurityContext, company_id: UUID) -> None:
        from erp.modules.procurement.application import PROCUREMENT_MATCHING_EXECUTE
        from erp.modules.workflow.application import WORKFLOW_REQUEST_CREATE

        await self._procurement.require(
            context, company_id, PROCUREMENT_MATCHING_EXECUTE, write=True
        )
        await self._workflow.require(context, company_id, WORKFLOW_REQUEST_CREATE, write=True)

    async def require_decision(self, context: SecurityContext, company_id: UUID) -> None:
        from erp.modules.procurement.application import PROCUREMENT_MATCHING_EXECUTE
        from erp.modules.workflow.application import WORKFLOW_APPROVAL_DECIDE

        await self._procurement.require(
            context, company_id, PROCUREMENT_MATCHING_EXECUTE, write=True
        )
        await self._workflow.require(context, company_id, WORKFLOW_APPROVAL_DECIDE, write=True)


class PostgresMatchingGovernanceOperations(MatchingGovernanceStore):
    """Own the transaction spanning matching, workflow, audit and outbox."""

    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def request_override(
        self,
        command: RequestMatchingOverride,
        *,
        actor_id: UUID,
        actor_permissions: frozenset[str],
    ) -> MatchingGovernanceResult:
        del actor_permissions
        try:
            validate_governance_version(command.expected_version, field="expected_version")
            justification = normalize_override_reason(command.justification, field="justification")
        except ValueError as error:
            raise _validation("Invalid matching override request.", error) from error
        async with self._database.session() as session, session.begin():
            replay = await self._idempotency.begin(
                session,
                scope=_scope(command.company_id, actor_id),
                operation="procurement.matching.override.request",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if replay.replayed:
                return await _replay_result(session, command.company_id, replay)

            aggregate = await _locked_matching(
                session, command.company_id, command.matching_session_id
            )
            _require_expected_version(aggregate.version, command.expected_version)
            amount = _override_amount(aggregate)
            fingerprint = _fingerprint(aggregate.id, aggregate.version)
            existing = await session.scalar(
                select(WorkflowInstanceModel).where(
                    WorkflowInstanceModel.company_id == command.company_id,
                    WorkflowInstanceModel.source_module == _SOURCE_MODULE,
                    WorkflowInstanceModel.source_type == _SOURCE_TYPE,
                    WorkflowInstanceModel.source_id == aggregate.id,
                    WorkflowInstanceModel.source_fingerprint == fingerprint,
                )
            )
            if existing is not None:
                raise ApplicationError(
                    code="MATCHING_OVERRIDE_ALREADY_REQUESTED",
                    message="An override workflow already exists for this matching version.",
                    status_code=409,
                )

            workflow_repository = WorkflowRepository(session, company_id=command.company_id)
            definition = await workflow_repository.find_active_definition(
                source_module=_SOURCE_MODULE,
                source_type=_SOURCE_TYPE,
            )
            if definition is None:
                raise _policy_not_configured("No active M22 matching override policy exists.")
            definitions = await workflow_repository.list_step_definitions(
                definition_id=definition.id
            )
            selected = _steps_for_amount(definitions, amount)
            workflow = WorkflowInstance.create(
                company_id=command.company_id,
                definition_id=definition.id,
                source_module=_SOURCE_MODULE,
                source_type=_SOURCE_TYPE,
                source_id=aggregate.id,
                source_fingerprint=fingerprint,
                requested_by=actor_id,
            )
            steps = _initial_steps(workflow, definition.approval_mode, selected)
            await workflow_repository.add_instance(workflow, steps=steps, actor_id=actor_id)
            event_id = await _record_matching_effect(
                session,
                event_type=MATCHING_OVERRIDE_REQUESTED,
                aggregate=aggregate,
                workflow_instance_id=workflow.id,
                actor_id=actor_id,
                reason=justification,
                discrepancy_amount=amount,
                metadata=command.metadata,
                before_status=aggregate.status.value,
                after_status=aggregate.status.value,
            )
            result = MatchingGovernanceResult(
                aggregate,
                _workflow_view(workflow, steps, amount),
                (event_id,),
            )
            await self._complete(session, replay, result)
            return result

    async def decide_override(
        self,
        command: DecideMatchingOverride,
        *,
        actor_id: UUID,
        actor_permissions: frozenset[str],
    ) -> MatchingGovernanceResult:
        try:
            validate_governance_version(command.expected_version, field="expected_version")
            validate_governance_version(
                command.workflow_expected_version,
                field="workflow_expected_version",
            )
            reason = normalize_override_reason(command.reason, field="reason")
        except ValueError as error:
            raise _validation("Invalid matching override decision.", error) from error
        async with self._database.session() as session, session.begin():
            replay = await self._idempotency.begin(
                session,
                scope=_scope(command.company_id, actor_id),
                operation=f"procurement.matching.override.{command.decision.value.lower()}",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if replay.replayed:
                return await _replay_result(session, command.company_id, replay)

            aggregate = await _locked_matching(
                session, command.company_id, command.matching_session_id
            )
            _require_expected_version(aggregate.version, command.expected_version)
            amount = _override_amount(aggregate)
            workflow_repository = WorkflowRepository(session, company_id=command.company_id)
            workflow = await workflow_repository.get_instance_for_update(
                command.workflow_instance_id
            )
            if workflow is None or not _workflow_belongs_to(workflow, aggregate.id):
                raise _not_found("Matching override workflow")
            if command.decision is MatchingOverrideDecision.APPROVE:
                await _enforce_sod(session, aggregate, actor_id)

            try:
                workflow_result = await apply_workflow_decision(
                    session,
                    DecideWorkflowInstance(
                        company_id=command.company_id,
                        workflow_instance_id=workflow.id,
                        step_instance_id=command.workflow_step_instance_id,
                        expected_version=command.workflow_expected_version,
                        decision=(
                            ApprovalDecisionKind.APPROVED
                            if command.decision is MatchingOverrideDecision.APPROVE
                            else ApprovalDecisionKind.REJECTED
                        ),
                        reason_code="MATCHING_OVERRIDE",
                        comment=reason,
                        metadata=CommandMetadata(
                            request_id=command.metadata.request_id,
                            correlation_id=command.metadata.correlation_id,
                            source_ip=command.metadata.source_ip,
                        ),
                    ),
                    actor_id=actor_id,
                    actor_permissions=actor_permissions,
                )
            except OptimisticLockError as error:
                raise ApplicationError(
                    code="VERSION_CONFLICT",
                    message="The matching override workflow was changed by another transaction.",
                    status_code=409,
                ) from error

            event_ids: list[UUID] = []
            if workflow_result.event_id is not None:
                event_ids.append(workflow_result.event_id)
            updated = aggregate
            final_status = workflow_result.detail.instance.status
            if final_status is WorkflowInstanceStatus.APPROVED:
                updated = aggregate.override(
                    decided_by=actor_id,
                    workflow_instance_id=workflow.id,
                    reason=reason,
                    occurred_at=datetime.now(UTC),
                )
                await ThreeWayMatchRepository(session, company_id=command.company_id).save(
                    updated, actor_id=actor_id, expected_version=aggregate.version
                )
                event_ids.append(
                    await _record_matching_effect(
                        session,
                        event_type=MATCHING_OVERRIDE_APPROVED,
                        aggregate=updated,
                        workflow_instance_id=workflow.id,
                        actor_id=actor_id,
                        reason=reason,
                        discrepancy_amount=amount,
                        metadata=command.metadata,
                        before_status=aggregate.status.value,
                        after_status=updated.status.value,
                    )
                )
            elif final_status is WorkflowInstanceStatus.REJECTED:
                updated = aggregate.reject(
                    decided_by=actor_id,
                    workflow_instance_id=workflow.id,
                    reason=reason,
                    occurred_at=datetime.now(UTC),
                )
                await ThreeWayMatchRepository(session, company_id=command.company_id).save(
                    updated, actor_id=actor_id, expected_version=aggregate.version
                )
                event_ids.append(
                    await _record_matching_effect(
                        session,
                        event_type=MATCHING_OVERRIDE_REJECTED,
                        aggregate=updated,
                        workflow_instance_id=workflow.id,
                        actor_id=actor_id,
                        reason=reason,
                        discrepancy_amount=amount,
                        metadata=command.metadata,
                        before_status=aggregate.status.value,
                        after_status=updated.status.value,
                    )
                )
            result = MatchingGovernanceResult(
                updated,
                _workflow_view(
                    workflow_result.detail.instance,
                    workflow_result.detail.steps,
                    amount,
                ),
                tuple(event_ids),
            )
            await self._complete(session, replay, result)
            return result

    async def _complete(
        self,
        session: AsyncSession,
        decision: IdempotencyDecision,
        result: MatchingGovernanceResult,
    ) -> None:
        await self._idempotency.complete(
            session,
            decision,
            response_status=200,
            response_body={
                "matching_session_id": str(result.session.id),
                "workflow_instance_id": str(result.workflow.id),
                "event_ids": [str(value) for value in result.event_ids],
            },
        )


async def _locked_matching(
    session: AsyncSession, company_id: UUID, matching_session_id: UUID
) -> ThreeWayMatchSession:
    locked = await session.scalar(
        select(MatchingSessionModel)
        .where(
            MatchingSessionModel.company_id == company_id,
            MatchingSessionModel.id == matching_session_id,
        )
        .with_for_update()
    )
    if locked is None:
        raise _not_found("Three-way matching session")
    aggregate = await ThreeWayMatchRepository(session, company_id=company_id).get(
        matching_session_id
    )
    if aggregate is None:
        raise _not_found("Three-way matching session")
    return aggregate


def _override_amount(aggregate: ThreeWayMatchSession) -> Decimal:
    if (
        aggregate.status is not ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED
        or aggregate.report is None
        or aggregate.report.status not in _ELIGIBLE_REPORTS
    ):
        raise ApplicationError(
            code="MATCHING_OVERRIDE_NOT_ELIGIBLE",
            message="Only price or tolerance discrepancies can request an override.",
            status_code=422,
        )
    amount = sum(
        (
            abs(result.unit_price_delta) * result.line.invoiced_quantity
            for result in aggregate.report.lines
            if result.status in _ELIGIBLE_REPORTS
        ),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise ApplicationError(
            code="MATCHING_OVERRIDE_NOT_ELIGIBLE",
            message="The matching discrepancy has no financial value to override.",
            status_code=422,
        )
    return amount


def _steps_for_amount(
    definitions: tuple[WorkflowStepDefinition, ...], amount: Decimal
) -> tuple[WorkflowStepDefinition, ...]:
    ordered = tuple(sorted(definitions, key=lambda value: value.sequence))
    for index, step in enumerate(ordered):
        if step.threshold_amount is None or amount <= step.threshold_amount:
            return ordered[: index + 1]
    raise _policy_not_configured(
        "The M22 matching override policy has no authority level for this discrepancy amount."
    )


def _initial_steps(
    instance: WorkflowInstance,
    mode: ApprovalMode,
    definitions: tuple[WorkflowStepDefinition, ...],
) -> tuple[WorkflowStepInstance, ...]:
    if not definitions:
        raise _policy_not_configured("The M22 matching override policy has no approval steps.")
    if mode is ApprovalMode.HIGHEST_LEVEL:
        active_sequences = {definitions[-1].sequence}
    elif mode is ApprovalMode.CUMULATIVE:
        active_sequences = {value.sequence for value in definitions}
    else:
        active_sequences = {definitions[0].sequence}
    return tuple(
        WorkflowStepInstance.create(
            company_id=instance.company_id,
            workflow_instance_id=instance.id,
            sequence=value.sequence,
            code=value.code,
            name=value.name,
            required_permission=value.required_permission,
            active=value.sequence in active_sequences,
        )
        for value in definitions
    )


async def _enforce_sod(
    session: AsyncSession,
    aggregate: ThreeWayMatchSession,
    actor_id: UUID,
) -> None:
    purchase_creator = await session.scalar(
        select(PurchaseOrderModel.created_by).where(
            PurchaseOrderModel.company_id == aggregate.company_id,
            PurchaseOrderModel.id == aggregate.purchase_order_snapshot.purchase_order.id,
        )
    )
    fiscal_creators = set(
        await session.scalars(
            select(InboundFiscalDocumentModel.created_by).where(
                InboundFiscalDocumentModel.company_id == aggregate.company_id,
                InboundFiscalDocumentModel.id.in_(
                    tuple(
                        value.id for value in aggregate.receiving_fiscal_snapshot.fiscal_documents
                    )
                ),
            )
        )
    )
    if actor_id == purchase_creator or actor_id in fiscal_creators:
        raise ApplicationError(
            code="SOD_VIOLATION",
            message=(
                "The purchase creator or inbound fiscal document issuer cannot approve "
                "its matching override."
            ),
            status_code=409,
        )


async def _record_matching_effect(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate: ThreeWayMatchSession,
    workflow_instance_id: UUID,
    actor_id: UUID,
    reason: str,
    discrepancy_amount: Decimal,
    metadata: ProcurementCommandMetadata,
    before_status: str,
    after_status: str,
) -> UUID:
    snapshot = {
        "matching_session_id": str(aggregate.id),
        "status": after_status,
        "version": aggregate.version,
        "workflow_instance_id": str(workflow_instance_id),
        "discrepancy_amount": str(discrepancy_amount),
        "currency": aggregate.purchase_order_snapshot.currency,
        "reason": reason,
    }
    await AuditService().record(
        session,
        AuditEvent(
            actor_user_id=actor_id,
            company_id=aggregate.company_id,
            branch_id=None,
            module="procurement",
            entity_type="three_way_match_session",
            entity_id=aggregate.id,
            operation=event_type,
            request_id=metadata.request_id,
            correlation_id=metadata.correlation_id,
            source_ip=metadata.source_ip,
            before_snapshot={"status": before_status},
            after_snapshot=snapshot,
            reason_code="MATCHING_OVERRIDE",
        ),
    )
    envelope = MessageEnvelope.new(
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=event_type,
        event_version=1,
        producer_module="procurement",
        producer_domain="procurement",
        aggregate_type="three_way_match_session",
        aggregate_id=aggregate.id,
        aggregate_version=aggregate.version,
        company_id=aggregate.company_id,
        branch_id=None,
        correlation_id=metadata.correlation_id,
        causation_id=None,
        request_id=metadata.request_id,
        payload=snapshot,
    )
    await OutboxService().enqueue(session, envelope)
    return envelope.message_id


async def _replay_result(
    session: AsyncSession,
    company_id: UUID,
    decision: IdempotencyDecision,
) -> MatchingGovernanceResult:
    body = decision.response_body or {}
    matching_id = body.get("matching_session_id")
    workflow_id = body.get("workflow_instance_id")
    if matching_id is None or workflow_id is None:
        raise RuntimeError("Stored matching governance replay is incomplete.")
    aggregate = await ThreeWayMatchRepository(session, company_id=company_id).get(
        UUID(str(matching_id))
    )
    workflow_repository = WorkflowRepository(session, company_id=company_id)
    workflow = await workflow_repository.get_instance(UUID(str(workflow_id)))
    if aggregate is None or workflow is None:
        raise RuntimeError("Stored matching governance replay references missing data.")
    steps = await workflow_repository.list_step_instances(workflow_instance_id=workflow.id)
    return MatchingGovernanceResult(
        aggregate,
        _workflow_view(workflow, steps, _override_amount_from_lines(aggregate)),
        tuple(UUID(str(value)) for value in body.get("event_ids", [])),
    )


def _override_amount_from_lines(aggregate: ThreeWayMatchSession) -> Decimal:
    if aggregate.report is None:
        raise RuntimeError("Stored matching governance replay has no report.")
    return sum(
        (
            abs(result.unit_price_delta) * result.line.invoiced_quantity
            for result in aggregate.report.lines
            if result.status in _ELIGIBLE_REPORTS
        ),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _workflow_view(
    workflow: WorkflowInstance,
    steps: tuple[WorkflowStepInstance, ...],
    amount: Decimal,
) -> MatchingWorkflowView:
    return MatchingWorkflowView(
        id=workflow.id,
        status=workflow.status.value,
        version=workflow.version,
        discrepancy_amount=amount,
        requested_by=workflow.requested_by,
        steps=tuple(
            MatchingWorkflowStepView(
                id=value.id,
                sequence=value.sequence,
                code=value.code,
                name=value.name,
                required_permission=value.required_permission,
                status=value.status.value,
                version=value.version,
            )
            for value in steps
        ),
    )


def _workflow_belongs_to(workflow: WorkflowInstance, matching_session_id: UUID) -> bool:
    return (
        workflow.source_module == _SOURCE_MODULE
        and workflow.source_type == _SOURCE_TYPE
        and workflow.source_id == matching_session_id
    )


def _require_expected_version(current: int, expected: int) -> None:
    if current != expected:
        raise ApplicationError(
            code="VERSION_CONFLICT",
            message="The matching session was changed by another transaction.",
            status_code=409,
            details=[ErrorDetail(message=f"Expected version {expected} is stale.")],
        )


def _fingerprint(matching_session_id: UUID, version: int) -> str:
    return f"matching-override:{matching_session_id}:v{version}"


def _scope(company_id: UUID, actor_id: UUID) -> str:
    return f"procurement-matching-governance:{company_id}:{actor_id}"


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND",
        message=f"{resource} not found.",
        status_code=404,
    )


def _policy_not_configured(message: str) -> ApplicationError:
    return ApplicationError(
        code="MATCHING_OVERRIDE_POLICY_NOT_CONFIGURED",
        message=message,
        status_code=409,
    )


def _validation(message: str, error: Exception) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message=message,
        status_code=422,
        details=[ErrorDetail(message=str(error))],
    )


__all__ = [
    "MATCHING_OVERRIDE_APPROVED",
    "MATCHING_OVERRIDE_REJECTED",
    "MATCHING_OVERRIDE_REQUESTED",
    "MatchingWorkflowAuthorization",
    "PostgresMatchingGovernanceOperations",
]
