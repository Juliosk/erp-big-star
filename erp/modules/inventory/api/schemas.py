"""Public inventory request and response schemas."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.inventory.domain import InventoryLotStatus, InventoryPoolKind


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


__all__ = [
    "CreateInventoryLotRequest",
    "CreateInventoryPoolRequest",
    "CreateLocationRequest",
    "CreateWarehouseRequest",
    "InventoryBalanceResponse",
    "InventoryLotListResponse",
    "InventoryLotResponse",
    "InventoryPoolListResponse",
    "InventoryPoolResponse",
    "PageMetadata",
    "WarehouseListResponse",
    "WarehouseLocationListResponse",
    "WarehouseLocationResponse",
    "WarehouseResponse",
]
