"""Public HTTP router for M2."""

from fastapi import APIRouter

from erp.modules.product.api.creation import router as creation_router
from erp.modules.product.api.queries import router as query_router

router = APIRouter()
router.include_router(query_router)
router.include_router(creation_router)

__all__ = ["router"]
