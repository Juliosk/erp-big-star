"""Inventory adjustment command endpoint."""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.api.creation import metadata
from erp.modules.inventory.api.schemas import InventoryBalanceResponse
from erp.modules.inventory.application.adjustments import InventoryAdjustmentService
from erp.modules.inventory.application.commands import (
    CreateInventoryAdjustment,
    InventoryAdjustmentLine,
    InventoryAdjustmentType,
)
from erp.modules.inventory.domain import InventoryState
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


class InventoryAdjustmentLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None = None
    lot_id: UUID | None = None
    pool_id: UUID | None = None
    state: InventoryState = InventoryState.AVAILABLE
    quantity: Decimal = Field(max_digits=18, decimal_places=6)


class CreateInventoryAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    adjustment_type: InventoryAdjustmentType
    reason: str = Field(min_length=3, max_length=500)
    lines: list[InventoryAdjustmentLineRequest] = Field(min_length=1, max_length=100)


class InventoryAdjustmentResponse(BaseModel):
    transaction_id: UUID
    balances: list[InventoryBalanceResponse]
    event_id: UUID | None
    audit_event_id: UUID | None
    idempotency_replayed: bool = False


def get_adjustments(request: Request) -> InventoryAdjustmentService:
    service = getattr(request.app.state, "inventory_adjustments", None)
    if not isinstance(service, InventoryAdjustmentService):
        raise ApplicationError(
            code="INVENTORY_ADJUSTMENT_UNAVAILABLE",
            message="Inventory adjustments unavailable.",
            status_code=503,
        )
    return service


@router.post("/adjustments", status_code=201, response_model=InventoryAdjustmentResponse)
async def create_adjustment(
    body: CreateInventoryAdjustmentRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryAdjustmentService, Depends(get_adjustments)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> InventoryAdjustmentResponse:
    command = CreateInventoryAdjustment(
        company_id=body.company_id,
        adjustment_type=body.adjustment_type,
        reason=body.reason,
        lines=tuple(
            InventoryAdjustmentLine(
                product_id=line.product_id,
                warehouse_id=line.warehouse_id,
                location_id=line.location_id,
                lot_id=line.lot_id,
                pool_id=line.pool_id,
                state=line.state,
                quantity=line.quantity,
            )
            for line in body.lines
        ),
        idempotency_key=idempotency_key,
        metadata=metadata(request),
    )
    result = await service.adjust(context, command)
    response.headers["Location"] = f"/api/v1/inventory/adjustments/{result.transaction_id}"
    response.headers["Idempotency-Replayed"] = str(result.idempotency_replayed).lower()
    response.headers["Cache-Control"] = "no-store"
    return InventoryAdjustmentResponse.model_validate(result.to_dict())


__all__ = [
    "CreateInventoryAdjustmentRequest",
    "InventoryAdjustmentLineRequest",
    "InventoryAdjustmentResponse",
    "get_adjustments",
    "router",
]
