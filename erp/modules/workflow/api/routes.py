"""Workflow Core HTTP endpoints for M22."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.workflow.api.schemas import (
    CreateWorkflowDefinitionRequest,
    PageMetadata,
    WorkflowDefinitionDetailResponse,
    WorkflowDefinitionListResponse,
    WorkflowDefinitionResponse,
    WorkflowStepDefinitionResponse,
)
from erp.modules.workflow.api.versioning import require_version
from erp.modules.workflow.application import (
    CreateWorkflowDefinition,
    CreateWorkflowStepDefinition,
    DeactivateWorkflowDefinition,
    WorkflowDefinitionDetail,
    WorkflowDefinitionService,
)
from erp.modules.workflow.domain import WorkflowDefinition, WorkflowStepDefinition
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])


def get_workflow_definitions(request: Request) -> WorkflowDefinitionService:
    service = getattr(request.app.state, "workflow_definitions", None)
    if not isinstance(service, WorkflowDefinitionService):
        raise ApplicationError(
            code="WORKFLOW_DEFINITION_UNAVAILABLE",
            message="Workflow definition service unavailable.",
            status_code=503,
        )
    return service


@router.get("/definitions", response_model=WorkflowDefinitionListResponse)
async def list_workflow_definitions(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[WorkflowDefinitionService, Depends(get_workflow_definitions)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    active: bool | None = None,
) -> WorkflowDefinitionListResponse:
    result = await service.list_definitions(
        context, company_id, active=active, page=page, page_size=page_size
    )
    response.headers["Cache-Control"] = "no-store"
    return WorkflowDefinitionListResponse(
        data=[_definition_response(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.post("/definitions", status_code=201, response_model=WorkflowDefinitionDetailResponse)
async def create_workflow_definition(
    body: CreateWorkflowDefinitionRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[WorkflowDefinitionService, Depends(get_workflow_definitions)],
) -> WorkflowDefinitionDetailResponse:
    result = await service.create_definition(
        context,
        CreateWorkflowDefinition(
            company_id=body.company_id,
            code=body.code,
            name=body.name,
            source_module=body.source_module,
            source_type=body.source_type,
            approval_mode=body.approval_mode,
            steps=tuple(
                CreateWorkflowStepDefinition(
                    sequence=step.sequence,
                    code=step.code,
                    name=step.name,
                    required_permission=step.required_permission,
                    threshold_amount=step.threshold_amount,
                )
                for step in body.steps
            ),
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/workflow/definitions/{result.definition.id}"
        f"?company_id={result.definition.company_id}"
    )
    response.headers["ETag"] = f'"{result.definition.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _definition_detail_response(result)


@router.get("/definitions/{definition_id}", response_model=WorkflowDefinitionDetailResponse)
async def get_workflow_definition(
    definition_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[WorkflowDefinitionService, Depends(get_workflow_definitions)],
) -> WorkflowDefinitionDetailResponse:
    result = await service.get_definition(context, company_id, definition_id)
    response.headers["ETag"] = f'"{result.definition.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _definition_detail_response(result)


@router.post(
    "/definitions/{definition_id}/deactivate",
    response_model=WorkflowDefinitionDetailResponse,
)
async def deactivate_workflow_definition(
    definition_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[WorkflowDefinitionService, Depends(get_workflow_definitions)],
    expected_version: Annotated[int, Depends(require_version)],
) -> WorkflowDefinitionDetailResponse:
    result = await service.deactivate_definition(
        context,
        DeactivateWorkflowDefinition(
            company_id=company_id,
            definition_id=definition_id,
            expected_version=expected_version,
        ),
    )
    response.headers["ETag"] = f'"{result.definition.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _definition_detail_response(result)


def _definition_detail_response(
    detail: WorkflowDefinitionDetail,
) -> WorkflowDefinitionDetailResponse:
    return WorkflowDefinitionDetailResponse(
        definition=_definition_response(detail.definition),
        steps=[_step_definition_response(step) for step in detail.steps],
    )


def _definition_response(definition: WorkflowDefinition) -> WorkflowDefinitionResponse:
    return WorkflowDefinitionResponse(
        id=definition.id,
        company_id=definition.company_id,
        code=definition.code,
        name=definition.name,
        source_module=definition.source_module,
        source_type=definition.source_type,
        approval_mode=definition.approval_mode,
        active=definition.active,
        version=definition.version,
    )


def _step_definition_response(
    step: WorkflowStepDefinition,
) -> WorkflowStepDefinitionResponse:
    return WorkflowStepDefinitionResponse(
        id=step.id,
        company_id=step.company_id,
        sequence=step.sequence,
        code=step.code,
        name=step.name,
        required_permission=step.required_permission,
        threshold_amount=(
            f"{step.threshold_amount:.2f}" if step.threshold_amount is not None else None
        ),
    )


__all__ = ["get_workflow_definitions", "router"]
