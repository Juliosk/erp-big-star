"""M12 Finance HTTP boundary."""

from fastapi import APIRouter

from erp.modules.finance.api.bank_reconciliation_routes import (
    router as reconciliation_router,
)
from erp.modules.finance.api.cash_flow_routes import router as cash_flow_router
from erp.modules.finance.api.routes import router as payable_router
from erp.modules.finance.api.treasury_routes import router as treasury_router

router = APIRouter()
router.include_router(payable_router)
router.include_router(treasury_router)
router.include_router(reconciliation_router)
router.include_router(cash_flow_router)

__all__ = ["router"]
