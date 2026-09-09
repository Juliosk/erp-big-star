"""Public HTTP router for M14."""

from fastapi import APIRouter

from erp.modules.customer.api.creation import router as creation_router
from erp.modules.customer.api.groups import router as group_router
from erp.modules.customer.api.queries import router as query_router
from erp.modules.customer.api.updates import router as update_router

router = APIRouter()
router.include_router(query_router)
router.include_router(creation_router)
router.include_router(update_router)
router.include_router(group_router)

__all__ = ["router"]
