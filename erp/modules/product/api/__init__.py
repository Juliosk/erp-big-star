"""Public HTTP router for M2."""

from fastapi import APIRouter

from erp.modules.product.api.barcodes import router as barcode_router
from erp.modules.product.api.creation import router as creation_router
from erp.modules.product.api.lifecycle import router as lifecycle_router
from erp.modules.product.api.queries import router as query_router
from erp.modules.product.api.updates import router as update_router

router = APIRouter()
router.include_router(query_router)
router.include_router(creation_router)
router.include_router(update_router)
router.include_router(lifecycle_router)
router.include_router(barcode_router)

__all__ = ["router"]
