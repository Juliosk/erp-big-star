"""Barcode application contracts and authorization."""

from dataclasses import asdict, dataclass
from typing import Any, Protocol
from uuid import UUID

from erp.modules.admin.contracts import SecurityContext
from erp.modules.product.application.commands import CommandMetadata, ProductCommandResult
from erp.modules.product.application.permissions import (
    PRODUCT_READ,
    PRODUCT_UPDATE,
    ProductAuthorization,
)
from erp.modules.product.domain.barcode import Barcode, BarcodeType
from erp.platform.errors import ApplicationError


@dataclass(frozen=True, slots=True)
class BarcodeView:
    id: UUID
    company_id: UUID
    product_id: UUID
    barcode_type: BarcodeType
    barcode: str


@dataclass(frozen=True, slots=True)
class AddBarcode:
    company_id: UUID
    product_id: UUID
    barcode_type: BarcodeType
    barcode: str
    expected_version: int
    idempotency_key: str
    metadata: CommandMetadata

    def payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "product_id": str(self.product_id),
            "barcode_type": self.barcode_type,
            "barcode": self.barcode,
            "expected_version": self.expected_version,
        }


@dataclass(frozen=True, slots=True)
class BarcodeResult:
    result: ProductCommandResult
    barcode: BarcodeView

    def to_dict(self) -> dict[str, object]:
        barcode = {key: str(value) for key, value in asdict(self.barcode).items()}
        return {**self.result.to_dict(), "barcode": barcode}

    @classmethod
    def replay(cls, body: dict[str, Any]) -> BarcodeResult:
        barcode = body["barcode"]
        return cls(
            ProductCommandResult.replay(body),
            BarcodeView(
                UUID(barcode["id"]),
                UUID(barcode["company_id"]),
                UUID(barcode["product_id"]),
                BarcodeType(barcode["barcode_type"]),
                barcode["barcode"],
            ),
        )


class BarcodeStore(Protocol):
    async def list(self, company_id: UUID, product_id: UUID) -> tuple[BarcodeView, ...]: ...
    async def add(self, command: AddBarcode, actor_id: UUID) -> BarcodeResult: ...


class ProductBarcodeService:
    def __init__(self, store: BarcodeStore, authorization: ProductAuthorization) -> None:
        self._store = store
        self._authorization = authorization

    async def list(
        self, context: SecurityContext, company_id: UUID, product_id: UUID
    ) -> tuple[BarcodeView, ...]:
        await self._authorization.require(context, company_id, PRODUCT_READ)
        return await self._store.list(company_id, product_id)

    async def add(self, context: SecurityContext, command: AddBarcode) -> BarcodeResult:
        await self._authorization.require(context, command.company_id, PRODUCT_UPDATE, write=True)
        try:
            Barcode(command.barcode_type, command.barcode)
        except ValueError as error:
            raise ApplicationError(
                code="INVALID_BARCODE", message=str(error), status_code=422
            ) from error
        return await self._store.add(command, context.principal.user_id)


__all__ = ["AddBarcode", "BarcodeResult", "BarcodeStore", "BarcodeView", "ProductBarcodeService"]
