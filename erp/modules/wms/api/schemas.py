"""Public WMS request and response schemas."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from erp.modules.wms.domain.picking import PickingTaskStatus, PickingWaveStatus


class PageMetadata(BaseModel):
    page: int
    page_size: int
    has_more: bool


class PickingTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    wave_id: UUID
    sequence: int
    product_id: UUID
    warehouse_id: UUID | None
    lot_id: UUID | None
    pool_id: UUID | None
    requested_quantity: str
    picked_quantity: str
    status: PickingTaskStatus
    version: int


class PickingWaveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    code: str
    status: PickingWaveStatus
    source_type: str
    source_id: UUID | None
    warehouse_id: UUID | None
    released_at: str | None
    released_by: UUID | None
    version: int


class PickingWaveDetailResponse(BaseModel):
    wave: PickingWaveResponse
    tasks: list[PickingTaskResponse]


class PickingWaveCommandResponse(BaseModel):
    detail: PickingWaveDetailResponse
    event_id: UUID | None = None
    audit_event_id: UUID | None = None
    idempotency_replayed: bool = False


class PickingTaskCommandResponse(BaseModel):
    task: PickingTaskResponse
    event_id: UUID | None = None
    audit_event_id: UUID | None = None
    idempotency_replayed: bool = False


class PickingWaveListResponse(BaseModel):
    data: list[PickingWaveResponse]
    meta: PageMetadata


class CreatePickingTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    zone_code: str = Field(default="DEFAULT", min_length=1, max_length=32)
    warehouse_id: UUID | None = None
    lot_id: UUID | None = None
    pool_id: UUID | None = None


class CreatePickingWaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    code: str = Field(min_length=1, max_length=64)
    source_type: str = Field(default="MANUAL", min_length=1, max_length=32)
    source_id: UUID | None = None
    warehouse_id: UUID | None = None
    items: list[CreatePickingTaskRequest] = Field(min_length=1, max_length=100)


class ScanPickingTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    barcode: str = Field(min_length=1, max_length=64)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)


__all__ = [
    "CreatePickingTaskRequest",
    "CreatePickingWaveRequest",
    "PageMetadata",
    "PickingTaskCommandResponse",
    "PickingTaskResponse",
    "PickingWaveCommandResponse",
    "PickingWaveDetailResponse",
    "PickingWaveListResponse",
    "PickingWaveResponse",
    "ScanPickingTaskRequest",
]
