"""Composition adapter joining M12 payment batches to M22 approvals."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application.treasury import TreasuryApprovalDecision
from erp.modules.finance.domain import PaymentBatch
from erp.modules.workflow.domain import (
    ApprovalDecisionKind,
    ApprovalMode,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowInstanceStatus,
    WorkflowStepDefinition,
    WorkflowStepInstance,
)
from erp.modules.workflow.infrastructure import WorkflowInstanceModel, WorkflowRepository
from erp.platform.errors import ApplicationError

_SOURCE_MODULE = "FINANCE"
_SOURCE_TYPE = "PAYMENT_BATCH"


class M22PaymentBatchApprovalGateway:
    """Open and verify tenant-scoped M22 workflows in the caller transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def request(self, batch: PaymentBatch, *, actor_id: UUID) -> UUID:
        repository = WorkflowRepository(self._session, company_id=batch.company_id)
        fingerprint = _fingerprint(batch)
        existing = await self._session.scalar(
            select(WorkflowInstanceModel).where(
                WorkflowInstanceModel.company_id == batch.company_id,
                WorkflowInstanceModel.source_module == _SOURCE_MODULE,
                WorkflowInstanceModel.source_type == _SOURCE_TYPE,
                WorkflowInstanceModel.source_id == batch.id,
                WorkflowInstanceModel.source_fingerprint == fingerprint,
            )
        )
        if existing is not None:
            return existing.id
        definition = await repository.find_active_definition(
            source_module=_SOURCE_MODULE,
            source_type=_SOURCE_TYPE,
        )
        if definition is None:
            raise _policy_not_configured()
        definitions = await repository.list_step_definitions(definition_id=definition.id)
        selected = _steps_for_amount(definitions, batch.total_amount)
        instance = WorkflowInstance.create(
            company_id=batch.company_id,
            definition_id=definition.id,
            source_module=_SOURCE_MODULE,
            source_type=_SOURCE_TYPE,
            source_id=batch.id,
            source_fingerprint=fingerprint,
            requested_by=actor_id,
        )
        await repository.add_instance(
            instance,
            steps=_initial_steps(instance, definition, selected),
            actor_id=actor_id,
        )
        return instance.id

    async def approved_decision(
        self,
        *,
        company_id: UUID,
        payment_batch_id: UUID,
        workflow_instance_id: UUID,
    ) -> TreasuryApprovalDecision:
        repository = WorkflowRepository(self._session, company_id=company_id)
        instance = await repository.get_instance(workflow_instance_id)
        if (
            instance is None
            or instance.source_module != _SOURCE_MODULE
            or instance.source_type != _SOURCE_TYPE
            or instance.source_id != payment_batch_id
        ):
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Payment-batch approval workflow not found.",
                status_code=404,
            )
        if instance.status is not WorkflowInstanceStatus.APPROVED:
            raise ApplicationError(
                code="PAYMENT_BATCH_APPROVAL_REQUIRED",
                message="The payment batch still requires an approved M22 decision.",
                status_code=409,
            )
        decisions = await repository.list_decisions(workflow_instance_id=instance.id)
        approved = tuple(
            value for value in decisions if value.decision is ApprovalDecisionKind.APPROVED
        )
        if not approved:
            raise ApplicationError(
                code="PAYMENT_BATCH_APPROVAL_REQUIRED",
                message="The approved M22 workflow has no approval evidence.",
                status_code=409,
            )
        final = max(approved, key=lambda value: (value.decided_at, value.id))
        return TreasuryApprovalDecision(instance.id, final.decided_by, final.decided_at)


def _steps_for_amount(
    definitions: tuple[WorkflowStepDefinition, ...],
    amount: Decimal,
) -> tuple[WorkflowStepDefinition, ...]:
    ordered = tuple(sorted(definitions, key=lambda value: value.sequence))
    for index, step in enumerate(ordered):
        if step.threshold_amount is None or amount <= step.threshold_amount:
            return ordered[: index + 1]
    raise _policy_not_configured()


def _initial_steps(
    instance: WorkflowInstance,
    definition: WorkflowDefinition,
    definitions: tuple[WorkflowStepDefinition, ...],
) -> tuple[WorkflowStepInstance, ...]:
    if not definitions:
        raise _policy_not_configured()
    if definition.approval_mode is ApprovalMode.HIGHEST_LEVEL:
        active = {definitions[-1].sequence}
    elif definition.approval_mode is ApprovalMode.CUMULATIVE:
        active = {value.sequence for value in definitions}
    else:
        active = {definitions[0].sequence}
    return tuple(
        WorkflowStepInstance.create(
            company_id=instance.company_id,
            workflow_instance_id=instance.id,
            sequence=value.sequence,
            code=value.code,
            name=value.name,
            required_permission=value.required_permission,
            active=value.sequence in active,
        )
        for value in definitions
    )


def _fingerprint(batch: PaymentBatch) -> str:
    return f"payment-batch:{batch.id}:v{batch.version}"


def _policy_not_configured() -> ApplicationError:
    return ApplicationError(
        code="PAYMENT_BATCH_APPROVAL_POLICY_NOT_CONFIGURED",
        message="No applicable M22 approval policy exists for payment batches.",
        status_code=409,
    )


__all__ = ["M22PaymentBatchApprovalGateway"]
