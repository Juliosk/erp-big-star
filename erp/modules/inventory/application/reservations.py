"""Reservation read ports and availability query service."""

from typing import Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.inventory.application.commands import (
    CreateInventoryReservation,
    InventoryReservationResult,
    ReleaseInventoryReservation,
)
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
from erp.platform.errors import ApplicationError, ErrorDetail


class InventoryReservationStore(Protocol):
    async def add(self, reservation: InventoryReservation) -> InventoryReservation: ...

    async def reserve(
        self, command: CreateInventoryReservation, actor_id: UUID
    ) -> InventoryReservationResult: ...

    async def release(
        self, command: ReleaseInventoryReservation, actor_id: UUID
    ) -> InventoryReservationResult: ...

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


class InventoryReservationService:
    """Authorize and execute critical reservation commands through M5 stores."""

    def __init__(
        self,
        store: InventoryReservationStore,
        authorization: InventoryAuthorization,
    ) -> None:
        self._store = store
        self._authorization = authorization

    async def reserve(
        self, context: SecurityContext, command: CreateInventoryReservation
    ) -> InventoryReservationResult:
        await self._authorization.require(
            context, command.company_id, INVENTORY_RESERVATION_MANAGE, write=True
        )
        _validate_reserve(command)
        try:
            return await self._store.reserve(command, context.principal.user_id)
        except ValueError as error:
            raise _validation(str(error)) from error

    async def release(
        self, context: SecurityContext, command: ReleaseInventoryReservation
    ) -> InventoryReservationResult:
        await self._authorization.require(
            context, command.company_id, INVENTORY_RESERVATION_MANAGE, write=True
        )
        if type(command.expected_version) is not int or command.expected_version < 1:
            raise _validation("expected_version must be a positive integer.")
        return await self._store.release(command, context.principal.user_id)


def _validate_page(page: int, page_size: int) -> None:
    if type(page) is not int or not 1 <= page <= 100_000:
        raise ApplicationError(code="VALIDATION_ERROR", message="Invalid page.", status_code=422)
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ApplicationError(
            code="VALIDATION_ERROR", message="Invalid page size.", status_code=422
        )


def _validate_reserve(command: CreateInventoryReservation) -> None:
    if not command.lines:
        raise _validation("At least one reservation line is required.")
    if not isinstance(command.reservation_kind, InventoryReservationKind):
        raise _validation("reservation_kind must be HARD or SOFT.")
    for line in command.lines:
        if line.quantity <= 0:
            raise _validation("reservation quantity must be positive.")
        try:
            InventoryState(line.state)
        except ValueError as error:
            raise _validation("state must be an official inventory state.") from error


def _validation(message: str) -> ApplicationError:
    return ApplicationError(
        code="BUSINESS_VALIDATION_ERROR",
        message="Invalid inventory reservation.",
        status_code=422,
        details=[ErrorDetail(message=message)],
    )


__all__ = [
    "InventoryAvailabilityDirectory",
    "InventoryAvailabilityQueryService",
    "InventoryReservationQueryService",
    "InventoryReservationService",
    "InventoryReservationStore",
]
