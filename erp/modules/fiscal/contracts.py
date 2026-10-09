"""Pure public integration contracts owned by M11 Fiscal."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from erp.modules.fiscal.domain import NFeAccessKey, TaxSnapshot
from erp.modules.fiscal.domain.exceptions import InvalidFiscalContractError


class FiscalOriginType(StrEnum):
    SALES_ORDER = "SALES_ORDER"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    GOODS_RECEIPT = "GOODS_RECEIPT"


@dataclass(frozen=True, slots=True)
class FiscalOriginReference:
    company_id: UUID
    source_type: FiscalOriginType
    source_id: UUID
    source_version: int

    def __post_init__(self) -> None:
        if self.source_version < 1:
            raise InvalidFiscalContractError("Fiscal source version must be positive.")


@dataclass(frozen=True, slots=True)
class AuthorizedFiscalDocumentFact:
    """Fact M12 may consume later without learning M11 internals."""

    company_id: UUID
    fiscal_document_id: UUID
    access_key: NFeAccessKey
    origin: FiscalOriginReference
    total_amount: Decimal
    tax_snapshot: TaxSnapshot

    def __post_init__(self) -> None:
        if self.origin.company_id != self.company_id:
            raise InvalidFiscalContractError("Fiscal origin must belong to the same company.")
        if not self.total_amount.is_finite() or self.total_amount < 0:
            raise InvalidFiscalContractError("Fiscal total amount must be finite and non-negative.")


@dataclass(frozen=True, slots=True)
class InboundPurchaseMatchReference:
    """M11-owned reference for later M6 physical/fiscal reconciliation."""

    company_id: UUID
    inbound_fiscal_document_id: UUID
    purchase_order_id: UUID
    goods_receipt_id: UUID | None
    supplier_tax_id: str
    access_key: NFeAccessKey
    total_amount: Decimal

    def __post_init__(self) -> None:
        identifiers = (
            self.company_id,
            self.inbound_fiscal_document_id,
            self.purchase_order_id,
        )
        if any(not isinstance(value, UUID) for value in identifiers) or (
            self.goods_receipt_id is not None
            and not isinstance(self.goods_receipt_id, UUID)
        ):
            raise InvalidFiscalContractError("Inbound purchase references must be UUIDs.")
        tax_id = "".join(character for character in self.supplier_tax_id if character.isdigit())
        if len(tax_id) not in {11, 14}:
            raise InvalidFiscalContractError("Inbound supplier tax ID is invalid.")
        if not self.total_amount.is_finite() or self.total_amount < 0:
            raise InvalidFiscalContractError(
                "Inbound fiscal total must be finite and non-negative."
            )
        object.__setattr__(self, "supplier_tax_id", tax_id)


__all__ = [
    "AuthorizedFiscalDocumentFact",
    "FiscalOriginReference",
    "FiscalOriginType",
    "InboundPurchaseMatchReference",
]
