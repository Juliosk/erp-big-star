"""Public HTTP router for M10 WMS."""

from fastapi import APIRouter

from erp.modules.wms.api.picking_waves import router as picking_wave_router

router = APIRouter()
router.include_router(picking_wave_router)

__all__ = ["router"]
