"""Public M15/M4 HTTP router."""

from fastapi import APIRouter

from erp.modules.sales.api.orders import router as order_router
from erp.modules.sales.api.routes import router as quote_router

router = APIRouter()
router.include_router(quote_router)
router.include_router(order_router)

__all__ = ["router"]
