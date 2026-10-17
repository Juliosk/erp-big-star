"""M12 Finance HTTP boundary."""

from fastapi import APIRouter

from erp.modules.finance.api.routes import router as payable_router
from erp.modules.finance.api.treasury_routes import router as treasury_router

router = APIRouter()
router.include_router(payable_router)
router.include_router(treasury_router)

__all__ = ["router"]
