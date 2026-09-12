"""Reservation read ports and availability query service."""

from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.application.permissions import (
    INVENTORY_AVAILABILITY_READ,
    INVENTORY_RESERVATION_MANAGE,
    InventoryAuthorization,
)
from erp.modules.inventory.application.queries import InventoryPage
from erp.modules.inventory.domain import (
    InventoryAvailability,
    InventoryReservation,
    InventoryReservationKind,
    InventoryReservationStatus,
    InventoryState,
)
from erp.platform.errors import ApplicationError


class InventoryReservationStore(Protocol):
    async def add(self, reservation: InventoryReservation) -> InventoryReservation: ...

    async def get(
        self, company_id: UUID, reservation_id: UUID
    ) -> InventoryReservation | None: ...

    async def list_reservations(
        self,
        company_id: UUID,
        *,
        status: InventoryReservationStatus | None,
        reservation_kind: InventoryReservationKind | None,
        page: int,
        page_size: int,
    ) -> InventoryPage[InventoryReservation]: ...


class InventoryAvailabilityDirectory(Protocol):
    async def list_availability(
        self,
        company_id: UUID,
        *,
        product_id: UUID | None,
        warehouse_id: UUID | None,
        lot_id: UUID | None,
        state: InventoryState | None,
        page: int,
        page_size: int,
    ) -> InventoryPage[InventoryAvailability]: ...


class InventoryAvailabilityQueryService:
    """Company-scoped ATP reads derived from balances and active reservations."""

    def __init__(
        self,
        directory: InventoryAvailabilityDirectory,
        authorization: InventoryAuthorization,
    ) -> None:
        self._directory = directory
        self._authorization = authorization

    async def list_availability(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        product_id: UUID | None = None,
        warehouse_id: UUID | None = None,
        lot_id: UUID | None = None,
        state: InventoryState | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> InventoryPage[InventoryAvailability]:
        await self._authorization.require(context, company_id, INVENTORY_AVAILABILITY_READ)
        _validate_page(page, page_size)
        if state is not None and not isinstance(state, InventoryState):
            raise ApplicationError(
                code="VALIDATION_ERROR", message="Invalid inventory state.", status_code=422
            )
        return await self._directory.list_availability(
            company_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            lot_id=lot_id,
            state=state,
            page=page,
            page_size=page_size,
        )


class InventoryReservationQueryService:
    """Authorized reservation reads for future API and order integration."""

    def __init__(
        self,
        store: InventoryReservationStore,
        authorization: InventoryAuthorization,
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def get(
        self, context: SecurityContext, company_id: UUID, reservation_id: UUID
    ) -> InventoryReservation:
        await self._authorization.require(context, company_id, INVENTORY_RESERVATION_MANAGE)
        reservation = await self._store.get(company_id, reservation_id)
        if reservation is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Inventory reservation not found.",
                status_code=404,
            )
        return reservation

    async def list_reservations(
        self,
        context: SecurityContext,
        company_id: UUID,
        *,
        status: InventoryReservationStatus | None = None,
        reservation_kind: InventoryReservationKind | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> InventoryPage[InventoryReservation]:
        await self._authorization.require(context, company_id, INVENTORY_RESERVATION_MANAGE)
        _validate_page(page, page_size)
        return await self._store.list_reservations(
            company_id,
            status=status,
            reservation_kind=reservation_kind,
            page=page,
            page_size=page_size,
        )


def _validate_page(page: int, page_size: int) -> None:
    if type(page) is not int or not 1 <= page <= 100_000:
        raise ApplicationError(code="VALIDATION_ERROR", message="Invalid page.", status_code=422)
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ApplicationError(
            code="VALIDATION_ERROR", message="Invalid page size.", status_code=422
        )


__all__ = [
    "InventoryAvailabilityDirectory",
    "InventoryAvailabilityQueryService",
    "InventoryReservationQueryService",
    "InventoryReservationStore",
]
