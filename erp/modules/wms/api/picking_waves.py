"""Picking-wave HTTP endpoints for M10 WMS."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.wms.api.schemas import (
    CreatePickingWaveRequest,
    PageMetadata,
    PickingTaskResponse,
    PickingWaveDetailResponse,
    PickingWaveListResponse,
    PickingWaveResponse,
)
from erp.modules.wms.application import (
    CreatePickingWave,
    PickingTaskBatchItem,
    PickingWaveDetail,
    PickingWaveService,
)
from erp.modules.wms.domain.picking import PickingTask, PickingWave, PickingWaveStatus
from erp.platform.errors import ApplicationError

router = APIRouter(prefix="/api/v1/wms", tags=["wms"])


def get_picking_waves(request: Request) -> PickingWaveService:
    service = getattr(request.app.state, "wms_picking_waves", None)
    if not isinstance(service, PickingWaveService):
        raise ApplicationError(
            code="WMS_PICKING_WAVE_UNAVAILABLE",
            message="WMS picking-wave service unavailable.",
            status_code=503,
        )
    return service


@router.get("/picking-waves", response_model=PickingWaveListResponse)
async def list_picking_waves(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PickingWaveService, Depends(get_picking_waves)],
    company_id: UUID,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    status: PickingWaveStatus | None = None,
) -> PickingWaveListResponse:
    result = await service.list_waves(
        context, company_id, status=status, page=page, page_size=page_size
    )
    response.headers["Cache-Control"] = "no-store"
    return PickingWaveListResponse(
        data=[_wave_response(item) for item in result.items],
        meta=PageMetadata(page=result.page, page_size=result.page_size, has_more=result.has_more),
    )


@router.post("/picking-waves", status_code=201, response_model=PickingWaveDetailResponse)
async def create_picking_wave(
    body: CreatePickingWaveRequest,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PickingWaveService, Depends(get_picking_waves)],
) -> PickingWaveDetailResponse:
    result = await service.create_wave(
        context,
        CreatePickingWave(
            company_id=body.company_id,
            code=body.code,
            source_type=body.source_type,
            source_id=body.source_id,
            warehouse_id=body.warehouse_id,
            items=tuple(
                PickingTaskBatchItem(
                    product_id=item.product_id,
                    quantity=item.quantity,
                    zone_code=item.zone_code,
                    warehouse_id=item.warehouse_id,
                    lot_id=item.lot_id,
                    pool_id=item.pool_id,
                )
                for item in body.items
            ),
        ),
    )
    response.headers["Location"] = (
        f"/api/v1/wms/picking-waves/{result.wave.id}?company_id={result.wave.company_id}"
    )
    response.headers["ETag"] = f'"{result.wave.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _detail_response(result)


@router.get("/picking-waves/{wave_id}", response_model=PickingWaveDetailResponse)
async def get_picking_wave(
    wave_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[PickingWaveService, Depends(get_picking_waves)],
) -> PickingWaveDetailResponse:
    result = await service.get_wave(context, company_id, wave_id)
    response.headers["ETag"] = f'"{result.wave.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _detail_response(result)


def _detail_response(detail: PickingWaveDetail) -> PickingWaveDetailResponse:
    return PickingWaveDetailResponse(
        wave=_wave_response(detail.wave),
        tasks=[_task_response(task) for task in detail.tasks],
    )


def _wave_response(wave: PickingWave) -> PickingWaveResponse:
    return PickingWaveResponse(
        id=wave.id,
        company_id=wave.company_id,
        code=wave.code,
        status=wave.status,
        source_type=wave.source_type,
        source_id=wave.source_id,
        warehouse_id=wave.warehouse_id,
        released_at=wave.released_at.isoformat() if wave.released_at is not None else None,
        released_by=wave.released_by,
        version=wave.version,
    )


def _task_response(task: PickingTask) -> PickingTaskResponse:
    return PickingTaskResponse(
        id=task.id,
        company_id=task.company_id,
        wave_id=task.wave_id,
        sequence=task.sequence,
        product_id=task.product_id,
        warehouse_id=task.warehouse_id,
        lot_id=task.lot_id,
        pool_id=task.pool_id,
        requested_quantity=f"{task.requested_quantity:.6f}",
        picked_quantity=f"{task.picked_quantity:.6f}",
        status=task.status,
        version=task.version,
    )


__all__ = ["get_picking_waves", "router"]
