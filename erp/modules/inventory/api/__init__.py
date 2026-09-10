"""Public HTTP router for M5."""

from fastapi import APIRouter

from erp.modules.inventory.api.creation import router as creation_router
from erp.modules.inventory.api.queries import router as query_router

router = APIRouter()
router.include_router(query_router)
router.include_router(creation_router)

__all__ = ["router"]
