"""M2 bulk import public port: immutable intent, preview and owner-controlled writes."""

from dataclasses import dataclass
from typing import Any, Protocol

from erp.modules.product.application.commands import CommandMetadata
from erp.modules.product.application.permissions import PRODUCT_READ, ProductAuthorization


@dataclass(frozen=True, slots=True)
class ProductImportRow:
    number: int
    values: dict[str, str]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProductImportPlan:
    number: int
    action: str
    current: dict[str, Any] | None
    proposed: dict[str, Any]
    differences: tuple[str, ...]
    errors: tuple[str, ...]


class ProductBulkDataAdapter(Protocol):
    async def authorize(self, plans: tuple[ProductImportPlan, ...]) -> None: ...

    async def validate(
        self, rows: tuple[ProductImportRow, ...]
    ) -> tuple[ProductImportPlan, ...]: ...

    async def commit(self, plans: tuple[ProductImportPlan, ...]) -> int: ...


__all__ = [
    "PRODUCT_READ",
    "CommandMetadata",
    "ProductAuthorization",
    "ProductBulkDataAdapter",
    "ProductImportPlan",
    "ProductImportRow",
]
