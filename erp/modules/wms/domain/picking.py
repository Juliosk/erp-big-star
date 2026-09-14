"""Picking waves and tasks owned by M10 WMS."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID, uuid4


class PickingWaveStatus(StrEnum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PickingTaskStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SHORTED = "SHORTED"
    CANCELLED = "CANCELLED"


def _require_uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise ValueError(f"{field} must be a UUID.")
    return value


def _normalize_code(value: str, field: str, *, max_length: int = 64) -> str:
    code = value.strip().upper()
    if not code or len(code) > max_length:
        raise ValueError(f"{field} must be 1-{max_length} characters.")
    if not code[0].isalnum() or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in code):
        raise ValueError(f"{field} must use uppercase alphanumeric code format.")
    return code


def _quantity(value: Decimal | str) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("quantity must be decimal with up to six places.") from exc
    if amount <= 0:
        raise ValueError("quantity must be positive.")
    return amount


@dataclass(frozen=True, slots=True)
class PickingWave:
    id: UUID
    company_id: UUID
    code: str
    status: PickingWaveStatus
    source_type: str
    source_id: UUID | None
    warehouse_id: UUID | None
    released_at: datetime | None
    released_by: UUID | None
    version: int

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        code: str,
        source_type: str = "MANUAL",
        source_id: UUID | None = None,
        warehouse_id: UUID | None = None,
    ) -> PickingWave:
        return cls(
            id=uuid4(),
            company_id=_require_uuid(company_id, "company_id"),
            code=_normalize_code(code, "code"),
            status=PickingWaveStatus.DRAFT,
            source_type=_normalize_code(source_type, "source_type", max_length=32),
            source_id=None if source_id is None else _require_uuid(source_id, "source_id"),
            warehouse_id=None
            if warehouse_id is None
            else _require_uuid(warehouse_id, "warehouse_id"),
            released_at=None,
            released_by=None,
            version=1,
        )

    def release(self, *, actor_id: UUID, now: datetime | None = None) -> PickingWave:
        if self.status is not PickingWaveStatus.DRAFT:
            raise ValueError("Only draft picking waves can be released.")
        return PickingWave(
            id=self.id,
            company_id=self.company_id,
            code=self.code,
            status=PickingWaveStatus.RELEASED,
            source_type=self.source_type,
            source_id=self.source_id,
            warehouse_id=self.warehouse_id,
            released_at=now or datetime.now(UTC),
            released_by=_require_uuid(actor_id, "actor_id"),
            version=self.version + 1,
        )

    def start(self) -> PickingWave:
        if self.status not in {PickingWaveStatus.RELEASED, PickingWaveStatus.IN_PROGRESS}:
            raise ValueError("Only released picking waves can start.")
        return PickingWave(
            id=self.id,
            company_id=self.company_id,
            code=self.code,
            status=PickingWaveStatus.IN_PROGRESS,
            source_type=self.source_type,
            source_id=self.source_id,
            warehouse_id=self.warehouse_id,
            released_at=self.released_at,
            released_by=self.released_by,
            version=self.version if self.status is PickingWaveStatus.IN_PROGRESS else self.version + 1,
        )


@dataclass(frozen=True, slots=True)
class PickingTask:
    id: UUID
    company_id: UUID
    wave_id: UUID
    product_id: UUID
    requested_quantity: Decimal
    picked_quantity: Decimal
    status: PickingTaskStatus
    version: int

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        wave_id: UUID,
        product_id: UUID,
        requested_quantity: Decimal | str,
    ) -> PickingTask:
        return cls(
            id=uuid4(),
            company_id=_require_uuid(company_id, "company_id"),
            wave_id=_require_uuid(wave_id, "wave_id"),
            product_id=_require_uuid(product_id, "product_id"),
            requested_quantity=_quantity(requested_quantity),
            picked_quantity=Decimal("0.000000"),
            status=PickingTaskStatus.OPEN,
            version=1,
        )

    def scan(self, quantity: Decimal | str) -> PickingTask:
        amount = _quantity(quantity)
        new_total = (self.picked_quantity + amount).quantize(Decimal("0.000001"))
        if new_total > self.requested_quantity:
            raise ValueError("picked quantity cannot exceed requested quantity.")
        return PickingTask(
            id=self.id,
            company_id=self.company_id,
            wave_id=self.wave_id,
            product_id=self.product_id,
            requested_quantity=self.requested_quantity,
            picked_quantity=new_total,
            status=(
                PickingTaskStatus.COMPLETED
                if new_total == self.requested_quantity
                else PickingTaskStatus.IN_PROGRESS
            ),
            version=self.version + 1,
        )


__all__ = [
    "PickingTask",
    "PickingTaskStatus",
    "PickingWave",
    "PickingWaveStatus",
]

