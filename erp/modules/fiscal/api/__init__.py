"""M11 fiscal HTTP boundary."""

from fastapi import APIRouter

from erp.modules.fiscal.api.inbound_routes import router as inbound_router
from erp.modules.fiscal.api.routes import router as document_router

router = APIRouter()
router.include_router(document_router)
router.include_router(inbound_router)

__all__ = ["router"]
