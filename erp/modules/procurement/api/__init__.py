"""M6 procurement HTTP boundary."""

from fastapi import APIRouter

from erp.modules.procurement.api.purchasing_routes import router as purchasing_router
from erp.modules.procurement.api.routes import router as supplier_router

router = APIRouter()
router.include_router(supplier_router)
router.include_router(purchasing_router)

__all__ = ["router"]
