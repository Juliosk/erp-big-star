"""Packing package primitives owned by M10 WMS."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.wms.domain.picking import _normalize_code, _require_uuid


class PackageStatus(StrEnum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    FINALIZED = "FINALIZED"
    DISPATCHED = "DISPATCHED"


class PackageType(StrEnum):
    CARTON = "CARTON"
    BAG = "BAG"
    PALLET = "PALLET"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class Package:
    id: UUID
    company_id: UUID
    package_code: str
    package_type: PackageType
    status: PackageStatus
    wave_id: UUID | None
    shipment_id: UUID | None
    weight_grams: int | None
    version: int

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        package_code: str,
        package_type: PackageType = PackageType.CARTON,
        wave_id: UUID | None = None,
        shipment_id: UUID | None = None,
        weight_grams: int | None = None,
    ) -> Package:
        if weight_grams is not None and (type(weight_grams) is not int or weight_grams <= 0):
            raise ValueError("weight_grams must be a positive integer.")
        return cls(
            id=uuid4(),
            company_id=_require_uuid(company_id, "company_id"),
            package_code=_normalize_code(package_code, "package_code"),
            package_type=package_type,
            status=PackageStatus.DRAFT,
            wave_id=None if wave_id is None else _require_uuid(wave_id, "wave_id"),
            shipment_id=None
            if shipment_id is None
            else _require_uuid(shipment_id, "shipment_id"),
            weight_grams=weight_grams,
            version=1,
        )

    def verify(self) -> Package:
        if self.status is not PackageStatus.DRAFT:
            raise ValueError("Only draft packages can be verified.")
        return Package(
            id=self.id,
            company_id=self.company_id,
            package_code=self.package_code,
            package_type=self.package_type,
            status=PackageStatus.VERIFIED,
            wave_id=self.wave_id,
            shipment_id=self.shipment_id,
            weight_grams=self.weight_grams,
            version=self.version + 1,
        )

    def finalize(self) -> Package:
        if self.status is not PackageStatus.VERIFIED:
            raise ValueError("Only verified packages can be finalized.")
        return Package(
            id=self.id,
            company_id=self.company_id,
            package_code=self.package_code,
            package_type=self.package_type,
            status=PackageStatus.FINALIZED,
            wave_id=self.wave_id,
            shipment_id=self.shipment_id,
            weight_grams=self.weight_grams,
            version=self.version + 1,
        )


@dataclass(frozen=True, slots=True)
class PackageItem:
    id: UUID
    company_id: UUID
    package_id: UUID
    task_id: UUID | None
    product_id: UUID
    lot_id: UUID | None
    quantity: Decimal

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        package_id: UUID,
        product_id: UUID,
        quantity: Decimal | str,
        task_id: UUID | None = None,
        lot_id: UUID | None = None,
    ) -> PackageItem:
        normalized_quantity = _normalize_quantity(quantity)
        if normalized_quantity <= 0:
            raise ValueError("quantity must be positive.")
        return cls(
            id=uuid4(),
            company_id=_require_uuid(company_id, "company_id"),
            package_id=_require_uuid(package_id, "package_id"),
            task_id=None if task_id is None else _require_uuid(task_id, "task_id"),
            product_id=_require_uuid(product_id, "product_id"),
            lot_id=None if lot_id is None else _require_uuid(lot_id, "lot_id"),
            quantity=normalized_quantity,
        )


def _normalize_quantity(value: Decimal | str) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("quantity must be a decimal value.") from error


__all__ = ["Package", "PackageItem", "PackageStatus", "PackageType"]
