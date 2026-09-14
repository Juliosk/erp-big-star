"""Public HTTP router for M10 WMS."""

from fastapi import APIRouter

from erp.modules.wms.api.packages import router as package_router
from erp.modules.wms.api.picking_tasks import router as picking_task_router
from erp.modules.wms.api.picking_waves import router as picking_wave_router

router = APIRouter()
router.include_router(picking_wave_router)
router.include_router(picking_task_router)
router.include_router(package_router)

__all__ = ["router"]
