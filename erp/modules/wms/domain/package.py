"""Packing package primitives owned by M10 WMS."""

from dataclasses import dataclass
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


__all__ = ["Package", "PackageStatus", "PackageType"]
