"""Pure M12 anti-corruption contracts for payable provisioning inputs."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID

from erp.modules.finance.domain import InvalidFinanceContractError

_CENT = Decimal("0.01")


def _uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidFinanceContractError(f"{field} must be a non-zero UUID.")
    return value


def _money(value: Decimal, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidFinanceContractError(f"{field} must be a finite Decimal.")
    try:
        normalized = value.quantize(_CENT)
    except InvalidOperation as error:
        raise InvalidFinanceContractError(
            f"{field} must use supported monetary precision."
        ) from error
    if normalized <= 0 or normalized != value:
        raise InvalidFinanceContractError(
            f"{field} must be positive with at most two decimal places."
        )
    return normalized


def _text(value: str, field: str, *, maximum: int) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized or len(normalized) > maximum:
        raise InvalidFinanceContractError(
            f"{field} must contain between 1 and {maximum} characters."
        )
    return normalized


def _tax_id(value: str) -> str:
    source = value if isinstance(value, str) else ""
    normalized = "".join(character for character in source if character.isdigit())
    if len(normalized) not in {11, 14}:
        raise InvalidFinanceContractError("supplier_tax_id must be a CPF or CNPJ.")
    return normalized


@dataclass(frozen=True, slots=True)
class AuthorizedFiscalDocumentReference:
    """Immutable M12 view of an M11-authorized supplier document."""

    company_id: UUID
    fiscal_document_id: UUID
    access_key: str
    authorization_protocol: str
    supplier_tax_id: str
    total_amount: Decimal

    def __post_init__(self) -> None:
        _uuid(self.company_id, "company_id")
        _uuid(self.fiscal_document_id, "fiscal_document_id")
        key = self.access_key.strip() if isinstance(self.access_key, str) else ""
        if len(key) != 44 or not key.isdigit():
            raise InvalidFinanceContractError("access_key must contain exactly 44 digits.")
        object.__setattr__(self, "access_key", key)
        object.__setattr__(
            self,
            "authorization_protocol",
            _text(self.authorization_protocol, "authorization_protocol", maximum=64),
        )
        object.__setattr__(self, "supplier_tax_id", _tax_id(self.supplier_tax_id))
        object.__setattr__(self, "total_amount", _money(self.total_amount, "total_amount"))


@dataclass(frozen=True, slots=True)
class ApprovedPurchaseOrderReference:
    """Immutable M12 view of an approved M6 purchase order."""

    company_id: UUID
    purchase_order_id: UUID
    supplier_id: UUID
    supplier_tax_id: str
    order_number: str
    approved_version: int
    total_amount: Decimal
    currency: str = "BRL"

    def __post_init__(self) -> None:
        _uuid(self.company_id, "company_id")
        _uuid(self.purchase_order_id, "purchase_order_id")
        _uuid(self.supplier_id, "supplier_id")
        object.__setattr__(self, "supplier_tax_id", _tax_id(self.supplier_tax_id))
        object.__setattr__(
            self, "order_number", _text(self.order_number, "order_number", maximum=64)
        )
        if type(self.approved_version) is not int or self.approved_version < 1:
            raise InvalidFinanceContractError("approved_version must be a positive integer.")
        object.__setattr__(self, "total_amount", _money(self.total_amount, "total_amount"))
        currency = self.currency.strip().upper() if isinstance(self.currency, str) else ""
        if len(currency) != 3 or not currency.isalpha() or not currency.isascii():
            raise InvalidFinanceContractError("currency must be a three-letter ASCII code.")
        object.__setattr__(self, "currency", currency)


@dataclass(frozen=True, slots=True)
class PayableProvisionRequest:
    """Tenant-bound provisioning request built after the M11/M6 integration gates."""

    request_id: UUID
    company_id: UUID
    requested_by: UUID
    fiscal_document: AuthorizedFiscalDocumentReference
    purchase_order: ApprovedPurchaseOrderReference

    def __post_init__(self) -> None:
        _uuid(self.request_id, "request_id")
        _uuid(self.company_id, "company_id")
        _uuid(self.requested_by, "requested_by")
        if not isinstance(self.fiscal_document, AuthorizedFiscalDocumentReference):
            raise InvalidFinanceContractError(
                "fiscal_document must be an authorized fiscal reference."
            )
        if not isinstance(self.purchase_order, ApprovedPurchaseOrderReference):
            raise InvalidFinanceContractError(
                "purchase_order must be an approved purchase order reference."
            )
        if (
            self.fiscal_document.company_id != self.company_id
            or self.purchase_order.company_id != self.company_id
        ):
            raise InvalidFinanceContractError(
                "Fiscal document, purchase order and provision must share company_id."
            )
        if self.fiscal_document.supplier_tax_id != self.purchase_order.supplier_tax_id:
            raise InvalidFinanceContractError(
                "Fiscal document and purchase order must reference the same supplier tax ID."
            )

    @property
    def fingerprint(self) -> str:
        return (
            f"M12:{self.company_id}:{self.fiscal_document.access_key}:"
            f"{self.purchase_order.purchase_order_id}:v{self.purchase_order.approved_version}"
        )


__all__ = [
    "ApprovedPurchaseOrderReference",
    "AuthorizedFiscalDocumentReference",
    "PayableProvisionRequest",
]
