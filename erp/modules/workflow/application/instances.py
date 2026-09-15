"""Application service for opening M22 workflow instances."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.workflow.application.definitions import WorkflowDefinitionDetail
from erp.modules.workflow.application.permissions import (
    WORKFLOW_REQUEST_CREATE,
    WORKFLOW_REQUEST_READ,
    WorkflowAuthorization,
)
from erp.modules.workflow.domain import (
    ApprovalMode,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStepDefinition,
    WorkflowStepInstance,
)
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class OpenWorkflowInstance:
    company_id: UUID
    source_module: str
    source_type: str
    source_id: UUID
    source_fingerprint: str


@dataclass(frozen=True, slots=True)
class WorkflowInstanceDetail:
    instance: WorkflowInstance
    steps: tuple[WorkflowStepInstance, ...]


class WorkflowInstanceStore(Protocol):
    async def open_instance(
        self, instance: WorkflowInstance, steps: tuple[WorkflowStepInstance, ...], actor_id: UUID
    ) -> WorkflowInstanceDetail: ...

    async def get_active_definition_for_source(
        self, company_id: UUID, *, source_module: str, source_type: str
    ) -> WorkflowDefinitionDetail | None: ...

    async def get_instance(
        self, company_id: UUID, workflow_instance_id: UUID
    ) -> WorkflowInstanceDetail | None: ...


class WorkflowInstanceService:
    """Authorize and open workflow instances without knowing source module internals."""

    def __init__(
        self,
        store: WorkflowInstanceStore,
        authorization: WorkflowAuthorization,
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def open_instance(
        self,
        context: SecurityContext,
        command: OpenWorkflowInstance,
    ) -> WorkflowInstanceDetail:
        await self._authorization.require(
            context, command.company_id, WORKFLOW_REQUEST_CREATE, write=True
        )
        try:
            normalized_probe = WorkflowInstance.create(
                company_id=command.company_id,
                definition_id=command.company_id,
                source_module=command.source_module,
                source_type=command.source_type,
                source_id=command.source_id,
                source_fingerprint=command.source_fingerprint,
                requested_by=context.principal.user_id,
            )
        except ValueError as error:
            raise _validation(str(error)) from error
        definition_detail = await self._store.get_active_definition_for_source(
            command.company_id,
            source_module=normalized_probe.source_module,
            source_type=normalized_probe.source_type,
        )
        if definition_detail is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Workflow definition not found for the requested source.",
                status_code=404,
            )
        instance = WorkflowInstance.create(
            company_id=command.company_id,
            definition_id=definition_detail.definition.id,
            source_module=command.source_module,
            source_type=command.source_type,
            source_id=command.source_id,
            source_fingerprint=command.source_fingerprint,
            requested_by=context.principal.user_id,
        )
        steps = _initial_steps(instance, definition_detail.definition, definition_detail.steps)
        return await self._store.open_instance(
            instance, steps, context.principal.user_id
        )

    async def get_instance(
        self,
        context: SecurityContext,
        company_id: UUID,
        workflow_instance_id: UUID,
    ) -> WorkflowInstanceDetail:
        await self._authorization.require(context, company_id, WORKFLOW_REQUEST_READ)
        detail = await self._store.get_instance(company_id, workflow_instance_id)
        if detail is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Workflow instance not found.",
                status_code=404,
            )
        return detail


def _initial_steps(
    instance: WorkflowInstance,
    definition: WorkflowDefinition,
    step_definitions: tuple[WorkflowStepDefinition, ...],
) -> tuple[WorkflowStepInstance, ...]:
    if not step_definitions:
        raise _validation("Workflow definition has no steps.")
    ordered = tuple(sorted(step_definitions, key=lambda step: step.sequence))
    if definition.approval_mode is ApprovalMode.HIGHEST_LEVEL:
        active_sequence = ordered[-1].sequence
        active_sequences = {active_sequence}
    elif definition.approval_mode is ApprovalMode.CUMULATIVE:
        active_sequences = {step.sequence for step in ordered}
    else:
        active_sequences = {ordered[0].sequence}
    return tuple(
        WorkflowStepInstance.create(
            company_id=instance.company_id,
            workflow_instance_id=instance.id,
            sequence=step.sequence,
            code=step.code,
            name=step.name,
            required_permission=step.required_permission,
            active=step.sequence in active_sequences,
        )
        for step in ordered
    )


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid workflow instance data.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = [
    "OpenWorkflowInstance",
    "WorkflowInstanceDetail",
    "WorkflowInstanceService",
    "WorkflowInstanceStore",
]
