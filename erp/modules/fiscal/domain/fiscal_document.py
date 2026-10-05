"""Pure aggregate for NF-e and NFC-e lifecycle and fiscal invariants."""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Self
from uuid import UUID, uuid4

from erp.modules.fiscal.domain.access_key import NFeAccessKey
from erp.modules.fiscal.domain.document import FiscalDocumentModel, FiscalDocumentStatus
from erp.modules.fiscal.domain.exceptions import (
    FiscalDomainError,
    ImmutableDocumentError,
    InvalidStateTransitionError,
    TaxMismatchError,
)
from erp.modules.fiscal.domain.tax_snapshot import MONEY_QUANTUM, TaxSnapshot

LEGAL_ROUNDING_TOLERANCE = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class FiscalPartySnapshot:
    tax_id: str
    legal_name: str
    state_registration: str | None
    street: str
    number: str
    district: str
    city: str
    state_code: str
    postal_code: str
    country_code: str = "BR"

    def __post_init__(self) -> None:
        tax_id = "".join(character for character in self.tax_id if character.isdigit())
        postal_code = "".join(
            character for character in self.postal_code if character.isdigit()
        )
        if len(tax_id) not in {11, 14}:
            raise FiscalDomainError("Fiscal party tax ID must be a CPF or CNPJ.")
        if not self.legal_name.strip() or not self.street.strip() or not self.city.strip():
            raise FiscalDomainError("Fiscal party name and address are required.")
        state = self.state_code.strip().upper()
        country = self.country_code.strip().upper()
        if len(state) != 2 or len(country) != 2 or len(postal_code) != 8:
            raise FiscalDomainError("Fiscal party state, country or postal code is invalid.")
        object.__setattr__(self, "tax_id", tax_id)
        object.__setattr__(self, "legal_name", self.legal_name.strip())
        object.__setattr__(self, "state_code", state)
        object.__setattr__(self, "country_code", country)
        object.__setattr__(self, "postal_code", postal_code)


@dataclass(frozen=True, slots=True)
class FiscalDocumentItem:
    id: UUID
    product_id: UUID
    code: str
    description: str
    ncm: str
    cfop: str
    unit_of_measure: str
    quantity: Decimal
    unit_price: Decimal
    freight_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    tax_snapshot: TaxSnapshot

    @classmethod
    def create(
        cls,
        *,
        product_id: UUID,
        code: str,
        description: str,
        ncm: str,
        cfop: str,
        unit_of_measure: str,
        quantity: Decimal | str,
        unit_price: Decimal | str,
        tax_snapshot: TaxSnapshot,
        freight_amount: Decimal | str = "0",
        discount_amount: Decimal | str = "0",
        total_amount: Decimal | str | None = None,
        item_id: UUID | None = None,
    ) -> Self:
        normalized_quantity = _decimal(quantity, QUANTITY_QUANTUM, "quantity")
        price = _money(unit_price, "unit price")
        freight = _money(freight_amount, "freight")
        discount = _money(discount_amount, "discount")
        if normalized_quantity <= 0 or price < 0 or freight < 0 or discount < 0:
            raise FiscalDomainError("Fiscal item quantities and amounts cannot be invalid.")
        gross = (normalized_quantity * price).quantize(MONEY_QUANTUM)
        calculated = gross - discount + freight
        if calculated < 0:
            raise FiscalDomainError("Fiscal item total cannot be negative.")
        supplied_total = calculated if total_amount is None else _money(total_amount, "item total")
        if abs(supplied_total - calculated) > LEGAL_ROUNDING_TOLERANCE:
            raise TaxMismatchError("Fiscal item total exceeds the legal rounding tolerance.")
        normalized = {
            "code": code.strip(),
            "description": description.strip(),
            "ncm": ncm.strip(),
            "cfop": cfop.strip(),
            "unit": unit_of_measure.strip().upper(),
        }
        if any(not value for value in normalized.values()):
            raise FiscalDomainError("Fiscal item classification and description are required.")
        return cls(
            id=item_id or uuid4(),
            product_id=product_id,
            code=normalized["code"],
            description=normalized["description"],
            ncm=normalized["ncm"],
            cfop=normalized["cfop"],
            unit_of_measure=normalized["unit"],
            quantity=normalized_quantity,
            unit_price=price,
            freight_amount=freight,
            discount_amount=discount,
            total_amount=supplied_total,
            tax_snapshot=tax_snapshot,
        )

    @property
    def products_amount(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(MONEY_QUANTUM)


@dataclass(frozen=True, slots=True)
class FiscalDocumentTotals:
    products_amount: Decimal
    freight_amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal

    @classmethod
    def create(
        cls,
        *,
        products_amount: Decimal | str,
        freight_amount: Decimal | str,
        discount_amount: Decimal | str,
        tax_amount: Decimal | str,
        total_amount: Decimal | str,
    ) -> Self:
        values = tuple(
            _money(value, field)
            for value, field in (
                (products_amount, "products total"),
                (freight_amount, "freight total"),
                (discount_amount, "discount total"),
                (tax_amount, "tax total"),
                (total_amount, "document total"),
            )
        )
        if any(value < 0 for value in values):
            raise FiscalDomainError("Fiscal document totals cannot be negative.")
        return cls(*values)

    @classmethod
    def from_items(cls, items: tuple[FiscalDocumentItem, ...]) -> Self:
        return cls(
            products_amount=_sum(item.products_amount for item in items),
            freight_amount=_sum(item.freight_amount for item in items),
            discount_amount=_sum(item.discount_amount for item in items),
            tax_amount=_sum(item.tax_snapshot.total_tax for item in items),
            total_amount=_sum(item.total_amount for item in items),
        )


@dataclass(frozen=True, slots=True)
class SefazResponseSnapshot:
    attempt_id: UUID
    status_code: str
    message: str
    occurred_at: datetime
    protocol: str | None = None

    def __post_init__(self) -> None:
        if not self.status_code.strip() or not self.message.strip():
            raise FiscalDomainError("SEFAZ response code and message are required.")
        object.__setattr__(self, "status_code", self.status_code.strip())
        object.__setattr__(self, "message", self.message.strip())
        if self.protocol is not None:
            normalized = self.protocol.strip()
            object.__setattr__(self, "protocol", normalized or None)


@dataclass(frozen=True, slots=True)
class FiscalDocument:
    id: UUID
    company_id: UUID
    model: FiscalDocumentModel
    series: int
    number: int
    issuer: FiscalPartySnapshot
    recipient: FiscalPartySnapshot
    items: tuple[FiscalDocumentItem, ...]
    totals: FiscalDocumentTotals
    status: FiscalDocumentStatus = FiscalDocumentStatus.DRAFT
    version: int = 1
    access_key: NFeAccessKey | None = None
    authorization_protocol: str | None = None
    rejection_code: str | None = None
    rejection_reason: str | None = None
    authorized_at: datetime | None = None
    cancellation_protocol: str | None = None
    cancelled_at: datetime | None = None
    sefaz_history: tuple[SefazResponseSnapshot, ...] = ()

    def __post_init__(self) -> None:
        if self.series < 1 or self.number < 1 or self.version < 1:
            raise FiscalDomainError("Fiscal series, number and version must be positive.")
        if not self.items:
            raise FiscalDomainError("Fiscal document requires at least one item.")
        if len({item.id for item in self.items}) != len(self.items):
            raise FiscalDomainError("Fiscal document item IDs must be unique.")
        _validate_totals(self.items, self.totals)
        final_identity = (
            self.access_key,
            self.authorization_protocol,
            self.authorized_at,
        )
        if self.status in {FiscalDocumentStatus.AUTHORIZED, FiscalDocumentStatus.CANCELLED}:
            if any(value is None for value in final_identity):
                raise FiscalDomainError("Authorized documents require access key and protocol.")
            assert self.access_key is not None
            if self.access_key.model != self.model.value:
                raise FiscalDomainError("Access key model does not match fiscal document model.")
        elif any(value is not None for value in final_identity):
            raise FiscalDomainError("Authorization identity is restricted to authorized documents.")
        if self.status in {FiscalDocumentStatus.REJECTED, FiscalDocumentStatus.DENIED}:
            if not self.rejection_code or not self.rejection_reason:
                raise FiscalDomainError("Rejected or denied documents require SEFAZ details.")
        elif self.rejection_code is not None or self.rejection_reason is not None:
            raise FiscalDomainError("SEFAZ rejection details do not match document state.")
        cancelled = self.status is FiscalDocumentStatus.CANCELLED
        if cancelled != (self.cancellation_protocol is not None and self.cancelled_at is not None):
            raise FiscalDomainError("Cancellation metadata does not match document state.")

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        model: FiscalDocumentModel,
        series: int,
        number: int,
        issuer: FiscalPartySnapshot,
        recipient: FiscalPartySnapshot,
        items: tuple[FiscalDocumentItem, ...],
        totals: FiscalDocumentTotals | None = None,
        document_id: UUID | None = None,
    ) -> Self:
        return cls(
            id=document_id or uuid4(),
            company_id=company_id,
            model=model,
            series=series,
            number=number,
            issuer=issuer,
            recipient=recipient,
            items=items,
            totals=totals or FiscalDocumentTotals.from_items(items),
        )

    def start_issuing(self) -> Self:
        self._require(FiscalDocumentStatus.DRAFT)
        return replace(self, status=FiscalDocumentStatus.ISSUING, version=self.version + 1)

    def authorize(
        self, *, access_key: NFeAccessKey, protocol: str, authorized_at: datetime
    ) -> Self:
        self._require(FiscalDocumentStatus.ISSUING)
        if not protocol.strip():
            raise FiscalDomainError("Authorization protocol is required.")
        return replace(
            self,
            status=FiscalDocumentStatus.AUTHORIZED,
            access_key=access_key,
            authorization_protocol=protocol.strip(),
            authorized_at=authorized_at,
            version=self.version + 1,
        )

    def reject(self, *, code: str, reason: str) -> Self:
        return self._complete_unsuccessfully(FiscalDocumentStatus.REJECTED, code, reason)

    def deny(self, *, code: str, reason: str) -> Self:
        return self._complete_unsuccessfully(FiscalDocumentStatus.DENIED, code, reason)

    def cancel(self, *, protocol: str, cancelled_at: datetime) -> Self:
        self._require(FiscalDocumentStatus.AUTHORIZED)
        if not protocol.strip():
            raise FiscalDomainError("Cancellation protocol is required.")
        return replace(
            self,
            status=FiscalDocumentStatus.CANCELLED,
            cancellation_protocol=protocol.strip(),
            cancelled_at=cancelled_at,
            version=self.version + 1,
        )

    def revise(self, *, items: tuple[FiscalDocumentItem, ...]) -> Self:
        if self.status in {FiscalDocumentStatus.AUTHORIZED, FiscalDocumentStatus.CANCELLED}:
            raise ImmutableDocumentError("Authorized or cancelled fiscal document is immutable.")
        self._require(FiscalDocumentStatus.DRAFT)
        return replace(
            self,
            items=items,
            totals=FiscalDocumentTotals.from_items(items),
            version=self.version + 1,
        )

    def _complete_unsuccessfully(
        self, status: FiscalDocumentStatus, code: str, reason: str
    ) -> Self:
        self._require(FiscalDocumentStatus.ISSUING)
        if not code.strip() or not reason.strip():
            raise FiscalDomainError("SEFAZ code and reason are required.")
        return replace(
            self,
            status=status,
            rejection_code=code.strip(),
            rejection_reason=reason.strip(),
            version=self.version + 1,
        )

    def _require(self, expected: FiscalDocumentStatus) -> None:
        if self.status is not expected:
            raise InvalidStateTransitionError(
                f"Fiscal document cannot transition from {self.status} as {expected}."
            )


def _validate_totals(
    items: tuple[FiscalDocumentItem, ...], totals: FiscalDocumentTotals
) -> None:
    calculated = FiscalDocumentTotals.from_items(items)
    fields = (
        (calculated.products_amount, totals.products_amount, "products"),
        (calculated.freight_amount, totals.freight_amount, "freight"),
        (calculated.discount_amount, totals.discount_amount, "discount"),
        (calculated.tax_amount, totals.tax_amount, "tax"),
        (calculated.total_amount, totals.total_amount, "document"),
    )
    for expected, actual, label in fields:
        if abs(expected - actual) > LEGAL_ROUNDING_TOLERANCE:
            raise TaxMismatchError(f"Fiscal {label} total exceeds legal rounding tolerance.")


def _decimal(value: Decimal | str, quantum: Decimal, field: str) -> Decimal:
    try:
        normalized = Decimal(value).quantize(quantum)
    except (InvalidOperation, ValueError) as error:
        raise FiscalDomainError(f"Invalid fiscal {field}.") from error
    if not normalized.is_finite():
        raise FiscalDomainError(f"Invalid fiscal {field}.")
    return normalized


def _money(value: Decimal | str, field: str) -> Decimal:
    return _decimal(value, MONEY_QUANTUM, field)


def _sum(values: Iterable[Decimal]) -> Decimal:
    return sum(values, start=Decimal("0.00")).quantize(MONEY_QUANTUM)


__all__ = [
    "LEGAL_ROUNDING_TOLERANCE",
    "FiscalDocument",
    "FiscalDocumentItem",
    "FiscalDocumentTotals",
    "FiscalPartySnapshot",
    "SefazResponseSnapshot",
]
