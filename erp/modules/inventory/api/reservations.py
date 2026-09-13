"""Inventory reservation and availability endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from erp.modules.admin.api import resolve_security_context
from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.api.creation import metadata
from erp.modules.inventory.api.schemas import (
    CreateInventoryReservationRequest,
    InventoryAvailabilityListResponse,
    InventoryAvailabilityResponse,
    InventoryReservationAllocationResponse,
    InventoryReservationCommandResponse,
    InventoryReservationListResponse,
    InventoryReservationResponse,
    PageMetadata,
)
from erp.modules.inventory.api.versioning import require_version
from erp.modules.inventory.application.commands import (
    CreateInventoryReservation,
    InventoryReservationLine,
    ReleaseInventoryReservation,
)
from erp.modules.inventory.application.reservations import (
    InventoryAvailabilityQueryService,
    InventoryReservationQueryService,
    InventoryReservationService,
)
from erp.modules.inventory.domain import (
    InventoryAvailability,
    InventoryReservation,
    InventoryReservationKind,
    InventoryReservationStatus,
    InventoryState,
)
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import require_idempotency_key

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


def get_reservation_commands(request: Request) -> InventoryReservationService:
    service = getattr(request.app.state, "inventory_reservations", None)
    if not isinstance(service, InventoryReservationService):
        raise ApplicationError(
            code="INVENTORY_RESERVATION_UNAVAILABLE",
            message="Inventory reservations unavailable.",
            status_code=503,
        )
    return service


def get_reservation_queries(request: Request) -> InventoryReservationQueryService:
    service = getattr(request.app.state, "inventory_reservation_queries", None)
    if not isinstance(service, InventoryReservationQueryService):
        raise ApplicationError(
            code="INVENTORY_RESERVATION_UNAVAILABLE",
            message="Inventory reservations unavailable.",
            status_code=503,
        )
    return service


def get_availability(request: Request) -> InventoryAvailabilityQueryService:
    service = getattr(request.app.state, "inventory_availability", None)
    if not isinstance(service, InventoryAvailabilityQueryService):
        raise ApplicationError(
            code="INVENTORY_AVAILABILITY_UNAVAILABLE",
            message="Inventory availability unavailable.",
            status_code=503,
        )
    return service


@router.get("/availability", response_model=InventoryAvailabilityListResponse)
async def list_availability(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryAvailabilityQueryService, Depends(get_availability)],
    company_id: UUID,
    product_id: UUID | None = None,
    warehouse_id: UUID | None = None,
    lot_id: UUID | None = None,
    state: InventoryState | None = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> InventoryAvailabilityListResponse:
    result = await service.list_availability(
        context,
        company_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        lot_id=lot_id,
        state=state,
        page=page,
        page_size=page_size,
    )
    response.headers["Cache-Control"] = "no-store"
    return InventoryAvailabilityListResponse(
        data=[_availability_response(item) for item in result.items],
        meta=PageMetadata(
            page=result.page, page_size=result.page_size, has_more=result.has_more
        ),
    )


@router.get("/reservations", response_model=InventoryReservationListResponse)
async def list_reservations(
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryReservationQueryService, Depends(get_reservation_queries)],
    company_id: UUID,
    status: InventoryReservationStatus | None = None,
    reservation_kind: InventoryReservationKind | None = None,
    page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> InventoryReservationListResponse:
    result = await service.list_reservations(
        context,
        company_id,
        status=status,
        reservation_kind=reservation_kind,
        page=page,
        page_size=page_size,
    )
    response.headers["Cache-Control"] = "no-store"
    return InventoryReservationListResponse(
        data=[_reservation_response(item) for item in result.items],
        meta=PageMetadata(
            page=result.page, page_size=result.page_size, has_more=result.has_more
        ),
    )


@router.post("/reservations", status_code=201, response_model=InventoryReservationCommandResponse)
async def create_reservation(
    body: CreateInventoryReservationRequest,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryReservationService, Depends(get_reservation_commands)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> InventoryReservationCommandResponse:
    result = await service.reserve(
        context,
        CreateInventoryReservation(
            company_id=body.company_id,
            reservation_kind=body.reservation_kind,
            reference_type=body.reference_type,
            reference_id=body.reference_id,
            expires_at=body.expires_at,
            lines=tuple(
                InventoryReservationLine(
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
        ),
    )
    _reservation_headers(response, result.reservation, replayed=result.idempotency_replayed)
    response.headers["Location"] = (
        f"/api/v1/inventory/reservations/{result.reservation.id}"
        f"?company_id={result.reservation.company_id}"
    )
    return InventoryReservationCommandResponse(
        reservation=_reservation_response(result.reservation),
        idempotency_replayed=result.idempotency_replayed,
    )


@router.get("/reservations/{reservation_id}", response_model=InventoryReservationResponse)
async def get_reservation(
    reservation_id: UUID,
    company_id: UUID,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryReservationQueryService, Depends(get_reservation_queries)],
) -> InventoryReservationResponse:
    reservation = await service.get(context, company_id, reservation_id)
    response.headers["ETag"] = f'"{reservation.version}"'
    response.headers["Cache-Control"] = "no-store"
    return _reservation_response(reservation)


@router.post(
    "/reservations/{reservation_id}/release",
    response_model=InventoryReservationCommandResponse,
)
async def release_reservation(
    reservation_id: UUID,
    company_id: UUID,
    request: Request,
    response: Response,
    context: Annotated[SecurityContext, Depends(resolve_security_context)],
    service: Annotated[InventoryReservationService, Depends(get_reservation_commands)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    version: Annotated[int, Depends(require_version)],
) -> InventoryReservationCommandResponse:
    result = await service.release(
        context,
        ReleaseInventoryReservation(
            company_id=company_id,
            reservation_id=reservation_id,
            expected_version=version,
            idempotency_key=idempotency_key,
            metadata=metadata(request),
        ),
    )
    _reservation_headers(response, result.reservation, replayed=result.idempotency_replayed)
    return InventoryReservationCommandResponse(
        reservation=_reservation_response(result.reservation),
        idempotency_replayed=result.idempotency_replayed,
    )


def _reservation_headers(
    response: Response, reservation: InventoryReservation, *, replayed: bool
) -> None:
    response.headers["ETag"] = f'"{reservation.version}"'
    response.headers["Idempotency-Replayed"] = str(replayed).lower()
    response.headers["Cache-Control"] = "no-store"


def _availability_response(item: InventoryAvailability) -> InventoryAvailabilityResponse:
    return InventoryAvailabilityResponse(
        company_id=item.company_id,
        product_id=item.product_id,
        warehouse_id=item.warehouse_id,
        location_id=item.location_id,
        lot_id=item.lot_id,
        pool_id=item.pool_id,
        state=item.state,
        on_hand=f"{item.on_hand.value:.6f}",
        hard_reserved=f"{item.hard_reserved.value:.6f}",
        soft_reserved=f"{item.soft_reserved.value:.6f}",
        available=f"{item.available.value:.6f}",
        version=item.version,
    )


def _reservation_response(item: InventoryReservation) -> InventoryReservationResponse:
    return InventoryReservationResponse(
        id=item.id,
        company_id=item.company_id,
        reservation_kind=item.reservation_kind,
        status=item.status,
        reference_type=item.reference_type,
        reference_id=item.reference_id,
        expires_at=item.expires_at,
        created_at=item.created_at,
        created_by=item.created_by,
        version=item.version,
        allocations=[
            InventoryReservationAllocationResponse(
                id=allocation.id,
                product_id=allocation.product_id,
                warehouse_id=allocation.warehouse_id,
                location_id=allocation.location_id,
                lot_id=allocation.lot_id,
                pool_id=allocation.pool_id,
                state=allocation.state,
                quantity=f"{allocation.quantity.value:.6f}",
            )
            for allocation in item.allocations
        ],
    )


__all__ = [
    "get_availability",
    "get_reservation_commands",
    "get_reservation_queries",
    "router",
]
