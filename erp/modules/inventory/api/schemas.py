"""Public inventory request and response schemas."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.inventory.domain import (
    InventoryLotStatus,
    InventoryPoolKind,
    InventoryReservationKind,
    InventoryReservationStatus,
)


class PageMetadata(BaseModel):
    page: int
    page_size: int
    has_more: bool


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    branch_id: UUID
    code: str
    name: str
    active: bool
    version: int


class WarehouseLocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    warehouse_id: UUID
    parent_location_id: UUID | None
    code: str
    name: str
    active: bool
    version: int


class InventoryPoolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    name: str
    kind: InventoryPoolKind
    active: bool
    version: int


class InventoryLotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    product_id: UUID
    code: str
    status: InventoryLotStatus
    expires_on: date | None
    version: int


class InventoryBalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    state: str
    quantity: str
    version: int


class InventoryPostingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    transaction_id: UUID
    sequence: int
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    state: str
    quantity_delta: str


class InventoryAvailabilityResponse(BaseModel):
    company_id: UUID
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    state: str
    on_hand: str
    hard_reserved: str
    soft_reserved: str
    available: str
    version: int


class InventoryReservationAllocationResponse(BaseModel):
    id: UUID
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    state: str
    quantity: str


class InventoryReservationResponse(BaseModel):
    id: UUID
    company_id: UUID
    reservation_kind: InventoryReservationKind
    status: InventoryReservationStatus
    reference_type: str
    reference_id: UUID
    expires_at: datetime | None
    created_at: datetime
    created_by: UUID
    version: int
    allocations: list[InventoryReservationAllocationResponse]


class WarehouseListResponse(BaseModel):
    data: list[WarehouseResponse]
    meta: PageMetadata


class WarehouseLocationListResponse(BaseModel):
    data: list[WarehouseLocationResponse]
    meta: PageMetadata


class InventoryPoolListResponse(BaseModel):
    data: list[InventoryPoolResponse]
    meta: PageMetadata


class InventoryLotListResponse(BaseModel):
    data: list[InventoryLotResponse]
    meta: PageMetadata


class InventoryBalanceListResponse(BaseModel):
    data: list[InventoryBalanceResponse]
    meta: PageMetadata


class InventoryAvailabilityListResponse(BaseModel):
    data: list[InventoryAvailabilityResponse]
    meta: PageMetadata


class InventoryPostingListResponse(BaseModel):
    data: list[InventoryPostingResponse]
    meta: PageMetadata


class InventoryReservationListResponse(BaseModel):
    data: list[InventoryReservationResponse]
    meta: PageMetadata


class InventoryReservationCommandResponse(BaseModel):
    reservation: InventoryReservationResponse
    idempotency_replayed: bool = False


class CreateWarehouseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    branch_id: UUID
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=120)


class CreateLocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    warehouse_id: UUID
    parent_location_id: UUID | None = None
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=120)


class CreateInventoryPoolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    kind: InventoryPoolKind


class CreateInventoryLotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    product_id: UUID
    code: str = Field(min_length=2, max_length=64)
    expires_on: date | None = None


class InventoryReservationLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    warehouse_id: UUID
    location_id: UUID | None = None
    lot_id: UUID | None = None
    pool_id: UUID | None = None
    state: str = "AVAILABLE"
    quantity: Decimal = Field(max_digits=18, decimal_places=6)


class CreateInventoryReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    reservation_kind: InventoryReservationKind
    reference_type: str = Field(min_length=2, max_length=64)
    reference_id: UUID
    expires_at: datetime | None = None
    lines: list[InventoryReservationLineRequest] = Field(min_length=1, max_length=100)


__all__ = [
    "CreateInventoryLotRequest",
    "CreateInventoryPoolRequest",
    "CreateInventoryReservationRequest",
    "CreateLocationRequest",
    "CreateWarehouseRequest",
    "InventoryAvailabilityListResponse",
    "InventoryAvailabilityResponse",
    "InventoryBalanceListResponse",
    "InventoryBalanceResponse",
    "InventoryLotListResponse",
    "InventoryLotResponse",
    "InventoryPoolListResponse",
    "InventoryPoolResponse",
    "InventoryPostingListResponse",
    "InventoryPostingResponse",
    "InventoryReservationAllocationResponse",
    "InventoryReservationCommandResponse",
    "InventoryReservationLineRequest",
    "InventoryReservationListResponse",
    "InventoryReservationResponse",
    "PageMetadata",
    "WarehouseListResponse",
    "WarehouseLocationListResponse",
    "WarehouseLocationResponse",
    "WarehouseResponse",
]
