"""Session-owning PostgreSQL adapter for M22 workflow definitions."""

from uuid import UUID

from erp.modules.workflow.application.definitions import (
    DeactivateWorkflowDefinition,
    WorkflowDefinitionDetail,
    WorkflowDefinitionStore,
    WorkflowPage,
)
from erp.modules.workflow.domain import WorkflowDefinition, WorkflowStepDefinition
from erp.modules.workflow.infrastructure.repository import WorkflowRepository
from erp.platform.database import Database
from erp.platform.errors import ApplicationError


class PostgresWorkflowDefinitions(WorkflowDefinitionStore):
    """Create, query and version workflow definitions through repositories."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_definition(
        self,
        definition: WorkflowDefinition,
        steps: tuple[WorkflowStepDefinition, ...],
        actor_id: UUID,
    ) -> WorkflowDefinitionDetail:
        async with self._database.session() as session, session.begin():
            repository = WorkflowRepository(session, company_id=definition.company_id)
            await repository.add_definition(definition, steps=steps, actor_id=actor_id)
        return WorkflowDefinitionDetail(definition=definition, steps=steps)

    async def list_definitions(
        self,
        company_id: UUID,
        *,
        active: bool | None,
        page: int,
        page_size: int,
    ) -> WorkflowPage[WorkflowDefinition]:
        offset = (page - 1) * page_size
        async with self._database.session() as session:
            repository = WorkflowRepository(session, company_id=company_id)
            items = await repository.list_definitions(
                active=active, limit=page_size, offset=offset
            )
            more = await repository.list_definitions(
                active=active, limit=1, offset=offset + page_size
            )
        return WorkflowPage(items=items, page=page, page_size=page_size, has_more=bool(more))

    async def get_definition(
        self, company_id: UUID, definition_id: UUID
    ) -> WorkflowDefinitionDetail | None:
        async with self._database.session() as session:
            repository = WorkflowRepository(session, company_id=company_id)
            definition = await repository.get_definition(definition_id)
            if definition is None:
                return None
            steps = await repository.list_step_definitions(definition_id=definition_id)
        return WorkflowDefinitionDetail(definition=definition, steps=steps)

    async def deactivate_definition(
        self, command: DeactivateWorkflowDefinition, actor_id: UUID
    ) -> WorkflowDefinitionDetail:
        async with self._database.session() as session, session.begin():
            repository = WorkflowRepository(session, company_id=command.company_id)
            definition = await repository.get_definition(command.definition_id)
            if definition is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Workflow definition not found.",
                    status_code=404,
                )
            deactivated = await repository.deactivate_definition(
                definition,
                actor_id=actor_id,
                expected_version=command.expected_version,
            )
            steps = await repository.list_step_definitions(definition_id=deactivated.id)
        return WorkflowDefinitionDetail(definition=deactivated, steps=steps)


__all__ = ["PostgresWorkflowDefinitions"]
