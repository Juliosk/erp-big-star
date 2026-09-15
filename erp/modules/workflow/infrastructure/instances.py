"""Session-owning PostgreSQL adapter for M22 workflow instances."""

from uuid import UUID

from erp.modules.workflow.application.definitions import WorkflowDefinitionDetail
from erp.modules.workflow.application.instances import (
    WorkflowInstanceDetail,
    WorkflowInstanceStore,
)
from erp.modules.workflow.domain import WorkflowInstance, WorkflowStepInstance
from erp.modules.workflow.infrastructure.repository import WorkflowRepository
from erp.platform.database import Database


class PostgresWorkflowInstances(WorkflowInstanceStore):
    """Open and query workflow instances through tenant-bound repositories."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def open_instance(
        self,
        instance: WorkflowInstance,
        steps: tuple[WorkflowStepInstance, ...],
        actor_id: UUID,
    ) -> WorkflowInstanceDetail:
        async with self._database.session() as session, session.begin():
            repository = WorkflowRepository(session, company_id=instance.company_id)
            await repository.add_instance(instance, steps=steps, actor_id=actor_id)
        return WorkflowInstanceDetail(instance=instance, steps=steps)

    async def get_active_definition_for_source(
        self, company_id: UUID, *, source_module: str, source_type: str
    ) -> WorkflowDefinitionDetail | None:
        async with self._database.session() as session:
            repository = WorkflowRepository(session, company_id=company_id)
            definition = await repository.find_active_definition(
                source_module=source_module, source_type=source_type
            )
            if definition is None:
                return None
            steps = await repository.list_step_definitions(definition_id=definition.id)
        return WorkflowDefinitionDetail(definition=definition, steps=steps)

    async def get_instance(
        self, company_id: UUID, workflow_instance_id: UUID
    ) -> WorkflowInstanceDetail | None:
        async with self._database.session() as session:
            repository = WorkflowRepository(session, company_id=company_id)
            instance = await repository.get_instance(workflow_instance_id)
            if instance is None:
                return None
            steps = await repository.list_step_instances(
                workflow_instance_id=workflow_instance_id
            )
        return WorkflowInstanceDetail(instance=instance, steps=steps)


__all__ = ["PostgresWorkflowInstances"]
