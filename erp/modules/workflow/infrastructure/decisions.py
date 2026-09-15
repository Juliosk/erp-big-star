"""Session-owning PostgreSQL adapter for M22 approval decisions."""

from uuid import UUID

from erp.modules.workflow.application.decisions import (
    DecideWorkflowInstance,
    WorkflowDecisionResult,
    WorkflowDecisionStore,
)
from erp.modules.workflow.application.instances import WorkflowInstanceDetail
from erp.modules.workflow.domain import (
    ApprovalDecision,
    ApprovalDecisionKind,
    ApprovalMode,
    WorkflowInstance,
    WorkflowStepInstance,
    WorkflowStepStatus,
)
from erp.modules.workflow.infrastructure.repository import WorkflowRepository
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError


class PostgresWorkflowDecisions(WorkflowDecisionStore):
    """Apply decisions, state progression and decision records atomically."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def decide(
        self,
        command: DecideWorkflowInstance,
        *,
        actor_id: UUID,
        actor_permissions: frozenset[str],
    ) -> WorkflowDecisionResult:
        async with self._database.session() as session, session.begin():
            repository = WorkflowRepository(session, company_id=command.company_id)
            instance = await repository.get_instance_for_update(command.workflow_instance_id)
            if instance is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Workflow instance not found.",
                    status_code=404,
                )
            if instance.version != command.expected_version:
                raise OptimisticLockError(expected_version=command.expected_version)
            definition = await repository.get_definition(instance.definition_id)
            if definition is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Workflow definition not found.",
                    status_code=404,
                )
            steps = await repository.list_step_instances(workflow_instance_id=instance.id)
            step = _selected_active_step(command, steps, actor_permissions)
            decided_step = _decide_step(command, step, actor_id)
            updated_step = await repository.update_step_instance(
                decided_step,
                actor_id=actor_id,
                expected_version=step.version,
            )
            updated_steps = tuple(
                updated_step if candidate.id == updated_step.id else candidate
                for candidate in steps
            )
            advanced_instance, advanced_steps = await _advance_workflow(
                repository,
                instance,
                updated_steps,
                mode=definition.approval_mode,
                decision=command.decision,
                actor_id=actor_id,
            )
            decision = ApprovalDecision.create(
                company_id=command.company_id,
                workflow_instance_id=instance.id,
                step_instance_id=updated_step.id,
                decision=command.decision,
                decided_by=actor_id,
                reason_code=command.reason_code,
                comment=command.comment,
                now=updated_step.decided_at,
            )
            await repository.add_decision(decision)
            return WorkflowDecisionResult(
                detail=WorkflowInstanceDetail(advanced_instance, advanced_steps),
                decision=decision,
            )


def _selected_active_step(
    command: DecideWorkflowInstance,
    steps: tuple[WorkflowStepInstance, ...],
    actor_permissions: frozenset[str],
) -> WorkflowStepInstance:
    for step in steps:
        if step.id == command.step_instance_id:
            if step.status is not WorkflowStepStatus.ACTIVE:
                raise ApplicationError(
                    code="WORKFLOW_STEP_STATUS_CONFLICT",
                    message="Only active workflow steps can be decided.",
                    status_code=409,
                )
            if step.required_permission not in actor_permissions:
                raise ApplicationError(
                    code="PERMISSION_FORBIDDEN",
                    message="The required approval-step permission was not granted.",
                    status_code=403,
                )
            return step
    raise ApplicationError(
        code="RESOURCE_NOT_FOUND",
        message="Workflow step instance not found.",
        status_code=404,
    )


def _decide_step(
    command: DecideWorkflowInstance,
    step: WorkflowStepInstance,
    actor_id: UUID,
) -> WorkflowStepInstance:
    try:
        if command.decision is ApprovalDecisionKind.REJECTED:
            return step.reject(actor_id=actor_id)
        return step.approve(actor_id=actor_id)
    except ValueError as error:
        raise ApplicationError(
            code="WORKFLOW_STEP_STATUS_CONFLICT",
            message="Workflow step cannot be decided.",
            status_code=409,
        ) from error


async def _advance_workflow(
    repository: WorkflowRepository,
    instance: WorkflowInstance,
    steps: tuple[WorkflowStepInstance, ...],
    *,
    mode: ApprovalMode,
    decision: ApprovalDecisionKind,
    actor_id: UUID,
) -> tuple[WorkflowInstance, tuple[WorkflowStepInstance, ...]]:
    if decision is ApprovalDecisionKind.REJECTED:
        rejected = instance.reject_final()
        updated = await repository.update_instance(
            rejected, actor_id=actor_id, expected_version=instance.version
        )
        return updated, steps
    if mode is ApprovalMode.SEQUENTIAL:
        return await _advance_sequential(repository, instance, steps, actor_id=actor_id)
    return await _advance_parallel_mode(repository, instance, steps, actor_id=actor_id)


async def _advance_sequential(
    repository: WorkflowRepository,
    instance: WorkflowInstance,
    steps: tuple[WorkflowStepInstance, ...],
    *,
    actor_id: UUID,
) -> tuple[WorkflowInstance, tuple[WorkflowStepInstance, ...]]:
    waiting = tuple(step for step in steps if step.status is WorkflowStepStatus.WAITING)
    if not waiting:
        approved = instance.approve_final()
        updated = await repository.update_instance(
            approved, actor_id=actor_id, expected_version=instance.version
        )
        return updated, steps
    next_step = min(waiting, key=lambda step: step.sequence)
    activated = next_step.activate()
    updated_next = await repository.update_step_instance(
        activated,
        actor_id=actor_id,
        expected_version=next_step.version,
    )
    advanced = instance.advance_to(updated_next.sequence)
    updated_instance = await repository.update_instance(
        advanced, actor_id=actor_id, expected_version=instance.version
    )
    updated_steps = tuple(
        updated_next if step.id == updated_next.id else step for step in steps
    )
    return updated_instance, updated_steps


async def _advance_parallel_mode(
    repository: WorkflowRepository,
    instance: WorkflowInstance,
    steps: tuple[WorkflowStepInstance, ...],
    *,
    actor_id: UUID,
) -> tuple[WorkflowInstance, tuple[WorkflowStepInstance, ...]]:
    remaining = tuple(step for step in steps if step.status is WorkflowStepStatus.ACTIVE)
    if not remaining:
        approved = instance.approve_final()
        updated = await repository.update_instance(
            approved, actor_id=actor_id, expected_version=instance.version
        )
        return updated, steps
    advanced = instance.advance_to(min(step.sequence for step in remaining))
    updated = await repository.update_instance(
        advanced, actor_id=actor_id, expected_version=instance.version
    )
    return updated, steps


__all__ = ["PostgresWorkflowDecisions"]
