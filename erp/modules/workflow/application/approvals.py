"""Application service for querying pending M22 approvals."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.workflow.application.definitions import WorkflowPage
from erp.modules.workflow.application.permissions import (
    WORKFLOW_REQUEST_READ,
    WorkflowAuthorization,
)
from erp.modules.workflow.domain import WorkflowInstance, WorkflowStepInstance
from erp.modules.workflow.domain.support import normalize_code
from erp.platform.errors import ApplicationError, ErrorDetail


@dataclass(frozen=True, slots=True)
class PendingApproval:
    step: WorkflowStepInstance
    instance: WorkflowInstance


class WorkflowApprovalStore(Protocol):
    async def list_pending_approvals(
        self,
        company_id: UUID,
        *,
        permissions: frozenset[str],
        source_module: str | None,
        source_type: str | None,
        page: int,
        page_size: int,
    ) -> WorkflowPage[PendingApproval]: ...


class WorkflowApprovalQueryService:
    """Return active approvals visible to the logged actor's permissions."""

    def __init__(
        self,
        store: WorkflowApprovalStore,
        authorization: WorkflowAuthorization,
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def list_pending(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        source_module: str | None = None,
        source_type: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> WorkflowPage[PendingApproval]:
        await self._authorization.require(context, company_id, WORKFLOW_REQUEST_READ)
        _validate_page(page, page_size)
        try:
            module_filter = (
                None
                if source_module is None
                else normalize_code(source_module, "source_module", max_length=32)
            )
            type_filter = (
                None
                if source_type is None
                else normalize_code(source_type, "source_type", max_length=64)
            )
        except ValueError as error:
            raise _validation(str(error)) from error
        return await self._store.list_pending_approvals(
            company_id,
            permissions=frozenset(str(permission) for permission in context.permissions),
            source_module=module_filter,
            source_type=type_filter,
            page=page,
            page_size=page_size,
        )


def _validate_page(page: int, page_size: int) -> None:
    if type(page) is not int or not 1 <= page <= 100_000:
        raise _validation("Invalid page.")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise _validation("Invalid page size.")


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid pending approval query.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = ["PendingApproval", "WorkflowApprovalQueryService", "WorkflowApprovalStore"]
