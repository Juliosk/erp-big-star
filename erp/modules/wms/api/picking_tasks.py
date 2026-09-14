"""Picking-task HTTP endpoints for M10 WMS."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.wms.api.picking_waves import _task_response, metadata
from erp.modules.wms.api.schemas import PickingTaskCommandResponse, ScanPickingTaskRequest
from erp.modules.wms.application import PickingTaskScanService, ScanPickingTask
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/wms", tags=["wms"])


def get_picking_tasks(request: Request) -> PickingTaskScanService:
    service = getattr(request.app.state, "wms_picking_tasks", None)
    if not isinstance(service, PickingTaskScanService):
        raise ApplicationError(
            code="WMS_PICKING_TASK_UNAVAILABLE",
            message="WMS picking-task service unavailable.",
            status_code=503,
        )
    return service


@router.post("/picking-tasks/{task_id}/scan", response_model=PickingTaskCommandResponse)
async def scan_picking_task(
    task_id: UUID,
    company_id: UUID,
    body: ScanPickingTaskRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PickingTaskScanService, Depends(get_picking_tasks)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> PickingTaskCommandResponse:
    result = await service.scan(
        context,
        ScanPickingTask(
            company_id=company_id,
            task_id=task_id,
            barcode=body.barcode,
            quantity=body.quantity,
            idempotency_key=idempotency_key,
            metadata=metadata(request),
        ),
    )
    response.headers["ETag"] = f'"{result.task.version}"'
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    response.headers["Cache-Control"] = "no-store"
    return PickingTaskCommandResponse(
        task=_task_response(result.task),
        event_id=result.event_id,
        audit_event_id=result.audit_event_id,
        idempotency_replayed=result.idempotency_replayed,
    )


__all__ = ["get_picking_tasks", "router"]
