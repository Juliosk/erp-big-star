"""Company-scoped PostgreSQL repositories for M22 Workflow Core aggregates."""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.workflow.domain import (
    ApprovalDecision,
    ApprovalDecisionKind,
    ApprovalMode,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowInstanceStatus,
    WorkflowStepDefinition,
    WorkflowStepInstance,
    WorkflowStepStatus,
)
from erp.modules.workflow.infrastructure.workflow_model import (
    ApprovalDecisionModel,
    WorkflowDefinitionModel,
    WorkflowInstanceModel,
    WorkflowStepDefinitionModel,
    WorkflowStepInstanceModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


def _require_company(company_id: UUID) -> None:
    if not isinstance(company_id, UUID):
        raise ValueError("An explicit company UUID is required.")


def _require_actor(actor_id: UUID) -> None:
    if not isinstance(actor_id, UUID):
        raise ValueError("An explicit actor UUID is required.")


def _validate_page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer.")


def _not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND",
        message=f"{resource} not found.",
        status_code=404,
    )


def _outside(resource: str) -> ApplicationError:
    return ApplicationError(
        code="SCOPE_FORBIDDEN",
        message=f"The {resource} is outside the selected company.",
        status_code=403,
    )


def _duplicate(error: IntegrityError, *, resource: str) -> ApplicationError | None:
    if getattr(error.orig, "sqlstate", None) == "23505":
        return ApplicationError(
            code=f"WORKFLOW_{resource.upper()}_CONFLICT",
            message=f"This workflow {resource.lower().replace('_', ' ')} already exists.",
            status_code=409,
        )
    return None


def _definition(model: WorkflowDefinitionModel) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=model.id,
        company_id=model.company_id,
        code=model.code,
        name=model.name,
        source_module=model.source_module,
        source_type=model.source_type,
        approval_mode=ApprovalMode(model.approval_mode),
        active=model.active,
        version=model.version,
    )


def _step_definition(model: WorkflowStepDefinitionModel) -> WorkflowStepDefinition:
    return WorkflowStepDefinition(
        id=model.id,
        company_id=model.company_id,
        sequence=model.sequence,
        code=model.code,
        name=model.name,
        required_permission=model.required_permission,
        threshold_amount=model.threshold_amount,
    )


def _instance(model: WorkflowInstanceModel) -> WorkflowInstance:
    return WorkflowInstance(
        id=model.id,
        company_id=model.company_id,
        definition_id=model.definition_id,
        source_module=model.source_module,
        source_type=model.source_type,
        source_id=model.source_id,
        source_fingerprint=model.source_fingerprint,
        status=WorkflowInstanceStatus(model.status),
        current_step_sequence=model.current_step_sequence,
        requested_by=model.requested_by,
        version=model.version,
    )


def _step_instance(model: WorkflowStepInstanceModel) -> WorkflowStepInstance:
    return WorkflowStepInstance(
        id=model.id,
        company_id=model.company_id,
        workflow_instance_id=model.workflow_instance_id,
        sequence=model.sequence,
        code=model.code,
        name=model.name,
        required_permission=model.required_permission,
        status=WorkflowStepStatus(model.status),
        activated_at=model.activated_at,
        decided_at=model.decided_at,
        decided_by=model.decided_by,
        version=model.version,
    )


def _decision(model: ApprovalDecisionModel) -> ApprovalDecision:
    return ApprovalDecision(
        id=model.id,
        company_id=model.company_id,
        workflow_instance_id=model.workflow_instance_id,
        step_instance_id=model.step_instance_id,
        decision=ApprovalDecisionKind(model.decision),
        decided_by=model.decided_by,
        decided_at=model.decided_at,
        reason_code=model.reason_code,
        comment=model.comment,
    )


class WorkflowRepository:
    """Persistence adapter for M22 records bounded by one selected company."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        _require_company(company_id)
        self._session = session
        self._company_id = company_id

    async def add_definition(
        self,
        definition: WorkflowDefinition,
        *,
        steps: Iterable[WorkflowStepDefinition],
        actor_id: UUID,
    ) -> None:
        _require_actor(actor_id)
        self._validate_scope(definition.company_id, "workflow definition")
        if definition.version != 1 or not definition.active:
            raise ValueError("A new workflow definition must start active at version one.")
        ordered_steps = tuple(sorted(steps, key=lambda step: step.sequence))
        if not ordered_steps:
            raise ValueError("A workflow definition requires at least one step.")
        if len({step.sequence for step in ordered_steps}) != len(ordered_steps):
            raise ValueError("Workflow step sequence must be unique.")
        self._session.add(
            WorkflowDefinitionModel(
                id=definition.id,
                company_id=self._company_id,
                code=definition.code,
                name=definition.name,
                source_module=definition.source_module,
                source_type=definition.source_type,
                approval_mode=definition.approval_mode,
                active=definition.active,
                version=definition.version,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        for step in ordered_steps:
            self._validate_scope(step.company_id, "workflow step definition")
            self._session.add(
                WorkflowStepDefinitionModel(
                    id=step.id,
                    company_id=self._company_id,
                    definition_id=definition.id,
                    sequence=step.sequence,
                    code=step.code,
                    name=step.name,
                    required_permission=step.required_permission,
                    threshold_amount=step.threshold_amount,
                    created_by=actor_id,
                )
            )
        await self._flush_unique(resource="DEFINITION")

    async def get_definition(self, definition_id: UUID) -> WorkflowDefinition | None:
        result = await self._session.scalars(
            select(WorkflowDefinitionModel).where(
                WorkflowDefinitionModel.company_id == self._company_id,
                WorkflowDefinitionModel.id == definition_id,
            ).execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _definition(model)

    async def find_active_definition(
        self, *, source_module: str, source_type: str
    ) -> WorkflowDefinition | None:
        result = await self._session.scalars(
            select(WorkflowDefinitionModel)
            .where(
                WorkflowDefinitionModel.company_id == self._company_id,
                WorkflowDefinitionModel.source_module == source_module,
                WorkflowDefinitionModel.source_type == source_type,
                WorkflowDefinitionModel.active.is_(True),
            )
            .order_by(WorkflowDefinitionModel.code, WorkflowDefinitionModel.id)
            .execution_options(populate_existing=True)
        )
        model = result.first()
        return None if model is None else _definition(model)

    async def list_definitions(
        self,
        *,
        active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[WorkflowDefinition, ...]:
        _validate_page(limit, offset)
        statement = select(WorkflowDefinitionModel).where(
            WorkflowDefinitionModel.company_id == self._company_id
        )
        if active is not None:
            statement = statement.where(WorkflowDefinitionModel.active.is_(active))
        result = await self._session.scalars(
            statement.order_by(WorkflowDefinitionModel.code, WorkflowDefinitionModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_definition(model) for model in result)

    async def list_step_definitions(
        self, *, definition_id: UUID
    ) -> tuple[WorkflowStepDefinition, ...]:
        result = await self._session.scalars(
            select(WorkflowStepDefinitionModel)
            .where(
                WorkflowStepDefinitionModel.company_id == self._company_id,
                WorkflowStepDefinitionModel.definition_id == definition_id,
            )
            .order_by(WorkflowStepDefinitionModel.sequence, WorkflowStepDefinitionModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_step_definition(model) for model in result)

    async def add_instance(
        self,
        instance: WorkflowInstance,
        *,
        steps: Iterable[WorkflowStepInstance],
        actor_id: UUID,
    ) -> None:
        _require_actor(actor_id)
        self._validate_scope(instance.company_id, "workflow instance")
        if instance.version != 1 or instance.status is not WorkflowInstanceStatus.PENDING:
            raise ValueError("A new workflow instance must start pending at version one.")
        await self._ensure_definition(instance.definition_id)
        ordered_steps = tuple(sorted(steps, key=lambda step: step.sequence))
        if not ordered_steps:
            raise ValueError("A workflow instance requires at least one step.")
        if len({step.sequence for step in ordered_steps}) != len(ordered_steps):
            raise ValueError("Workflow step sequence must be unique.")
        self._session.add(
            WorkflowInstanceModel(
                id=instance.id,
                company_id=self._company_id,
                definition_id=instance.definition_id,
                source_module=instance.source_module,
                source_type=instance.source_type,
                source_id=instance.source_id,
                source_fingerprint=instance.source_fingerprint,
                status=instance.status,
                current_step_sequence=instance.current_step_sequence,
                requested_by=instance.requested_by,
                version=instance.version,
                updated_by=actor_id,
            )
        )
        for step in ordered_steps:
            self._validate_scope(step.company_id, "workflow step instance")
            if step.workflow_instance_id != instance.id:
                raise ValueError("Workflow step instance must belong to its instance.")
            self._session.add(
                WorkflowStepInstanceModel(
                    id=step.id,
                    company_id=self._company_id,
                    workflow_instance_id=instance.id,
                    sequence=step.sequence,
                    code=step.code,
                    name=step.name,
                    required_permission=step.required_permission,
                    status=step.status,
                    activated_at=step.activated_at,
                    decided_at=step.decided_at,
                    decided_by=step.decided_by,
                    version=step.version,
                    updated_by=actor_id,
                )
            )
        await self._flush_unique(resource="INSTANCE")

    async def get_instance(self, workflow_instance_id: UUID) -> WorkflowInstance | None:
        result = await self._session.scalars(
            select(WorkflowInstanceModel).where(
                WorkflowInstanceModel.company_id == self._company_id,
                WorkflowInstanceModel.id == workflow_instance_id,
            ).execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _instance(model)

    async def get_instance_for_update(
        self, workflow_instance_id: UUID
    ) -> WorkflowInstance | None:
        result = await self._session.scalars(
            select(WorkflowInstanceModel)
            .where(
                WorkflowInstanceModel.company_id == self._company_id,
                WorkflowInstanceModel.id == workflow_instance_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _instance(model)

    async def list_instances(
        self,
        *,
        status: WorkflowInstanceStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[WorkflowInstance, ...]:
        _validate_page(limit, offset)
        statement = select(WorkflowInstanceModel).where(
            WorkflowInstanceModel.company_id == self._company_id
        )
        if status is not None:
            statement = statement.where(WorkflowInstanceModel.status == status)
        result = await self._session.scalars(
            statement.order_by(WorkflowInstanceModel.created_at, WorkflowInstanceModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_instance(model) for model in result)

    async def list_step_instances(
        self, *, workflow_instance_id: UUID
    ) -> tuple[WorkflowStepInstance, ...]:
        result = await self._session.scalars(
            select(WorkflowStepInstanceModel)
            .where(
                WorkflowStepInstanceModel.company_id == self._company_id,
                WorkflowStepInstanceModel.workflow_instance_id == workflow_instance_id,
            )
            .order_by(WorkflowStepInstanceModel.sequence, WorkflowStepInstanceModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_step_instance(model) for model in result)

    async def list_active_steps_for_permissions(
        self,
        permissions: frozenset[str],
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[WorkflowStepInstance, ...]:
        _validate_page(limit, offset)
        if not permissions:
            return ()
        result = await self._session.scalars(
            select(WorkflowStepInstanceModel)
            .where(
                WorkflowStepInstanceModel.company_id == self._company_id,
                WorkflowStepInstanceModel.status == WorkflowStepStatus.ACTIVE,
                WorkflowStepInstanceModel.required_permission.in_(permissions),
            )
            .order_by(WorkflowStepInstanceModel.activated_at, WorkflowStepInstanceModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_step_instance(model) for model in result)

    async def update_instance(
        self,
        instance: WorkflowInstance,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> WorkflowInstance:
        _require_actor(actor_id)
        self._validate_scope(instance.company_id, "workflow instance")
        result = await self._session.scalars(
            update(WorkflowInstanceModel)
            .where(
                WorkflowInstanceModel.company_id == self._company_id,
                WorkflowInstanceModel.id == instance.id,
                WorkflowInstanceModel.version == expected_version,
            )
            .values(
                status=instance.status,
                current_step_sequence=instance.current_step_sequence,
                updated_by=actor_id,
                version=WorkflowInstanceModel.version + 1,
            )
            .returning(WorkflowInstanceModel)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        model = result.one_or_none()
        if model is None:
            raise OptimisticLockError(expected_version=expected_version)
        await self._session.flush()
        return _instance(model)

    async def update_step_instance(
        self,
        step: WorkflowStepInstance,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> WorkflowStepInstance:
        _require_actor(actor_id)
        self._validate_scope(step.company_id, "workflow step instance")
        result = await self._session.scalars(
            update(WorkflowStepInstanceModel)
            .where(
                WorkflowStepInstanceModel.company_id == self._company_id,
                WorkflowStepInstanceModel.id == step.id,
                WorkflowStepInstanceModel.version == expected_version,
            )
            .values(
                status=step.status,
                activated_at=step.activated_at,
                decided_at=step.decided_at,
                decided_by=step.decided_by,
                updated_by=actor_id,
                version=WorkflowStepInstanceModel.version + 1,
            )
            .returning(WorkflowStepInstanceModel)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        model = result.one_or_none()
        if model is None:
            raise OptimisticLockError(expected_version=expected_version)
        await self._session.flush()
        return _step_instance(model)

    async def add_decision(self, decision: ApprovalDecision) -> None:
        self._validate_scope(decision.company_id, "approval decision")
        await self._ensure_instance(decision.workflow_instance_id)
        await self._ensure_step_instance(decision.step_instance_id)
        self._session.add(
            ApprovalDecisionModel(
                id=decision.id,
                company_id=self._company_id,
                workflow_instance_id=decision.workflow_instance_id,
                step_instance_id=decision.step_instance_id,
                decision=decision.decision,
                decided_by=decision.decided_by,
                decided_at=decision.decided_at,
                reason_code=decision.reason_code,
                comment=decision.comment,
            )
        )
        await self._flush_unique(resource="DECISION")

    async def list_decisions(
        self, *, workflow_instance_id: UUID
    ) -> tuple[ApprovalDecision, ...]:
        result = await self._session.scalars(
            select(ApprovalDecisionModel)
            .where(
                ApprovalDecisionModel.company_id == self._company_id,
                ApprovalDecisionModel.workflow_instance_id == workflow_instance_id,
            )
            .order_by(ApprovalDecisionModel.decided_at, ApprovalDecisionModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(_decision(model) for model in result)

    async def _flush_unique(self, *, resource: str) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            conflict = _duplicate(error, resource=resource)
            if conflict is not None:
                raise conflict from error
            raise

    def _validate_scope(self, company_id: UUID, resource: str) -> None:
        if company_id != self._company_id:
            raise _outside(resource)

    async def _exists(self, model: Any, model_id: UUID) -> bool:
        value = await self._session.scalar(
            select(1).select_from(model).where(
                model.company_id == self._company_id,
                model.id == model_id,
            )
        )
        return value is not None

    async def _ensure_definition(self, definition_id: UUID) -> None:
        if not await self._exists(WorkflowDefinitionModel, definition_id):
            raise _not_found("Workflow definition")

    async def _ensure_instance(self, workflow_instance_id: UUID) -> None:
        if not await self._exists(WorkflowInstanceModel, workflow_instance_id):
            raise _not_found("Workflow instance")

    async def _ensure_step_instance(self, step_instance_id: UUID) -> None:
        if not await self._exists(WorkflowStepInstanceModel, step_instance_id):
            raise _not_found("Workflow step instance")


__all__ = [
    "WorkflowRepository",
    "_decision",
    "_definition",
    "_instance",
    "_step_definition",
    "_step_instance",
]
