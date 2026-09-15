"""Application service for M22 workflow definition management."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import PermissionCode, SecurityContext
from erp.modules.workflow.application.permissions import (
    WORKFLOW_DEFINITION_MANAGE,
    WorkflowAuthorization,
)
from erp.modules.workflow.domain import (
    ApprovalMode,
    WorkflowDefinition,
    WorkflowStepDefinition,
)
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class WorkflowPage[T]:
    items: tuple[T, ...]
    page: int
    page_size: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class CreateWorkflowStepDefinition:
    sequence: int
    code: str
    name: str
    required_permission: str
    threshold_amount: Decimal | str | None = None


@dataclass(frozen=True, slots=True)
class CreateWorkflowDefinition:
    company_id: UUID
    code: str
    name: str
    source_module: str
    source_type: str
    approval_mode: ApprovalMode
    steps: tuple[CreateWorkflowStepDefinition, ...]


@dataclass(frozen=True, slots=True)
class DeactivateWorkflowDefinition:
    company_id: UUID
    definition_id: UUID
    expected_version: int


@dataclass(frozen=True, slots=True)
class WorkflowDefinitionDetail:
    definition: WorkflowDefinition
    steps: tuple[WorkflowStepDefinition, ...]


class WorkflowAuthorizer(Protocol):
    async def require(
        self,
        context: SecurityContext,
        company_id: UUID,
        permission: PermissionCode,
        *,
        write: bool = False,
    ) -> None: ...


class WorkflowDefinitionStore(Protocol):
    async def create_definition(
        self,
        definition: WorkflowDefinition,
        steps: tuple[WorkflowStepDefinition, ...],
        actor_id: UUID,
    ) -> WorkflowDefinitionDetail: ...

    async def list_definitions(
        self,
        company_id: UUID,
        *,
        active: bool | None,
        page: int,
        page_size: int,
    ) -> WorkflowPage[WorkflowDefinition]: ...

    async def get_definition(
        self, company_id: UUID, definition_id: UUID
    ) -> WorkflowDefinitionDetail | None: ...

    async def deactivate_definition(
        self, command: DeactivateWorkflowDefinition, actor_id: UUID
    ) -> WorkflowDefinitionDetail: ...


class WorkflowDefinitionService:
    """Authorize and manage reusable approval definitions."""

    def __init__(
        self,
        store: WorkflowDefinitionStore,
        authorization: WorkflowAuthorization,
    ) -> None:
        self._store = store
        self._authorization: WorkflowAuthorizer = authorization

    async def create_definition(
        self,
        context: SecurityContext,
        command: CreateWorkflowDefinition,
    ) -> WorkflowDefinitionDetail:
        await self._authorization.require(
            context, command.company_id, WORKFLOW_DEFINITION_MANAGE, write=True
        )
        if not command.steps:
            raise _validation("A workflow definition requires at least one step.")
        try:
            definition = WorkflowDefinition.create(
                company_id=command.company_id,
                code=command.code,
                name=command.name,
                source_module=command.source_module,
                source_type=command.source_type,
                approval_mode=command.approval_mode,
            )
            steps = tuple(
                WorkflowStepDefinition.create(
                    company_id=command.company_id,
                    sequence=step.sequence,
                    code=step.code,
                    name=step.name,
                    required_permission=step.required_permission,
                    threshold_amount=step.threshold_amount,
                )
                for step in command.steps
            )
        except ValueError as error:
            raise _validation(str(error)) from error
        return await self._store.create_definition(
            definition, steps, context.principal.user_id
        )

    async def list_definitions(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        active: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> WorkflowPage[WorkflowDefinition]:
        await self._authorization.require(
            context, company_id, WORKFLOW_DEFINITION_MANAGE
        )
        _validate_page(page, page_size)
        return await self._store.list_definitions(
            company_id, active=active, page=page, page_size=page_size
        )

    async def get_definition(
        self, context: SecurityContext, company_id: UUID, definition_id: UUID
    ) -> WorkflowDefinitionDetail:
        await self._authorization.require(
            context, company_id, WORKFLOW_DEFINITION_MANAGE
        )
        detail = await self._store.get_definition(company_id, definition_id)
        if detail is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Workflow definition not found.",
                status_code=404,
            )
        return detail

    async def deactivate_definition(
        self,
        context: SecurityContext,
        command: DeactivateWorkflowDefinition,
    ) -> WorkflowDefinitionDetail:
        await self._authorization.require(
            context, command.company_id, WORKFLOW_DEFINITION_MANAGE, write=True
        )
        return await self._store.deactivate_definition(
            command, context.principal.user_id
        )


def _validate_page(page: int, page_size: int) -> None:
    if type(page) is not int or not 1 <= page <= 100_000:
        raise _validation("Invalid page.")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise _validation("Invalid page size.")


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid workflow definition data.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = [
    "CreateWorkflowDefinition",
    "CreateWorkflowStepDefinition",
    "DeactivateWorkflowDefinition",
    "WorkflowDefinitionDetail",
    "WorkflowDefinitionService",
    "WorkflowDefinitionStore",
    "WorkflowPage",
]
