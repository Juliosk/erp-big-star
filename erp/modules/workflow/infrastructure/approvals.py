"""Session-owning PostgreSQL adapter for M22 pending approvals."""

from uuid import UUID

from erp.modules.workflow.application.approvals import (
    PendingApproval,
    WorkflowApprovalStore,
)
from erp.modules.workflow.application.definitions import WorkflowPage
from erp.modules.workflow.infrastructure.repository import WorkflowRepository
from erp.platform.database import Database


class PostgresWorkflowApprovals(WorkflowApprovalStore):
    """Query active workflow approval steps visible to the current actor."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_pending_approvals(
        self,
        company_id: UUID,
        *,
        permissions: frozenset[str],
        source_module: str | None,
        source_type: str | None,
        page: int,
        page_size: int,
    ) -> WorkflowPage[PendingApproval]:
        offset = (page - 1) * page_size
        async with self._database.session() as session:
            repository = WorkflowRepository(session, company_id=company_id)
            rows = await repository.list_pending_approvals(
                permissions=permissions,
                source_module=source_module,
                source_type=source_type,
                limit=page_size,
                offset=offset,
            )
            more = await repository.list_pending_approvals(
                permissions=permissions,
                source_module=source_module,
                source_type=source_type,
                limit=1,
                offset=offset + page_size,
            )
        return WorkflowPage(
            items=tuple(PendingApproval(step=step, instance=instance) for step, instance in rows),
            page=page,
            page_size=page_size,
            has_more=bool(more),
        )


__all__ = ["PostgresWorkflowApprovals"]
