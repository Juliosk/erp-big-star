"""Composition adapter for the M12 payable approval policy and M22 runtime."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import FINANCE_PAYABLE_APPROVE
from erp.modules.finance.domain import Payable
from erp.modules.finance.infrastructure.approval_gateway import PayableApprovalPlan
from erp.modules.workflow.domain import (
    ApprovalMode,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStepDefinition,
    WorkflowStepInstance,
)
from erp.modules.workflow.infrastructure.repository import WorkflowRepository
from erp.platform.errors import ApplicationError


class M22PayableApprovalGateway:
    """Open M22 instances inside the caller's transaction when authority is insufficient."""

    async def plan(
        self,
        session: AsyncSession,
        *,
        payable: Payable,
        actor_id: UUID,
        granted_permissions: frozenset[str],
    ) -> PayableApprovalPlan:
        repository = WorkflowRepository(session, company_id=payable.company_id)
        definition = await repository.find_active_definition(
            source_module="FINANCE", source_type="PAYABLE"
        )
        if definition is None:
            raise ApplicationError(
                code="PAYABLE_APPROVAL_POLICY_NOT_CONFIGURED",
                message="No active M22 approval policy exists for payables.",
                status_code=409,
            )
        steps = await repository.list_step_definitions(definition_id=definition.id)
        if not steps:
            raise ApplicationError(
                code="PAYABLE_APPROVAL_POLICY_NOT_CONFIGURED",
                message="The active M22 payable policy has no approval steps.",
                status_code=409,
            )
        sod_threshold = min(
            (value.threshold_amount for value in steps if value.threshold_amount is not None),
            default=Decimal("0.01"),
        )
        matching = tuple(
            value
            for value in steps
            if value.required_permission in granted_permissions
            and str(FINANCE_PAYABLE_APPROVE) in granted_permissions
        )
        unlimited = any(value.threshold_amount is None for value in matching)
        authority_limit = (
            None
            if unlimited
            else max(
                (
                    value.threshold_amount
                    for value in matching
                    if value.threshold_amount is not None
                ),
                default=Decimal("0.00"),
            )
        )
        over_limit = authority_limit is not None and payable.total_amount > authority_limit
        sod_requires_workflow = (
            payable.created_by == actor_id and payable.total_amount >= sod_threshold
        )
        if not matching or over_limit or sod_requires_workflow:
            instance = WorkflowInstance.create(
                company_id=payable.company_id,
                definition_id=definition.id,
                source_module="FINANCE",
                source_type="PAYABLE",
                source_id=payable.id,
                source_fingerprint=f"payable:{payable.id}:v{payable.version}",
                requested_by=actor_id,
            )
            initial_steps = _initial_steps(instance, definition, steps)
            await repository.add_instance(instance, steps=initial_steps, actor_id=actor_id)
            return PayableApprovalPlan(instance.id, authority_limit, sod_threshold)
        return PayableApprovalPlan(None, authority_limit, sod_threshold)


def _initial_steps(
    instance: WorkflowInstance,
    definition: WorkflowDefinition,
    definitions: tuple[WorkflowStepDefinition, ...],
) -> tuple[WorkflowStepInstance, ...]:
    ordered = tuple(sorted(definitions, key=lambda value: value.sequence))
    if definition.approval_mode is ApprovalMode.HIGHEST_LEVEL:
        active = {ordered[-1].sequence}
    elif definition.approval_mode is ApprovalMode.CUMULATIVE:
        active = {value.sequence for value in ordered}
    else:
        active = {ordered[0].sequence}
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
        for value in ordered
    )


__all__ = ["M22PayableApprovalGateway"]
