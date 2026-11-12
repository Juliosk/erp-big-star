"""Pure M6 request-for-quotation aggregate and supplier quote snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from erp.modules.procurement.domain.exceptions import (
    InvalidRequestForQuotationError,
    InvalidRequestForQuotationTransitionError,
    RequestForQuotationSodViolationError,
)
from erp.modules.procurement.domain.support import (
    currency,
    identifier,
    money,
    quantity,
    require_uuid,
    text,
)


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise InvalidRequestForQuotationError(f"{field} must be timezone-aware.")
    return value


class RequestForQuotationStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class RequestForQuotationItem:
    id: UUID
    product_id: UUID
    quantity: Decimal
    uom: str
    required_on: date
    specification: str

    def __post_init__(self) -> None:
        require_uuid(self.id, "id")
        require_uuid(self.product_id, "product_id")
        object.__setattr__(self, "quantity", quantity(self.quantity))
        object.__setattr__(self, "uom", identifier(self.uom, "uom", maximum=8))
        if not isinstance(self.required_on, date):
            raise InvalidRequestForQuotationError("required_on must be a date.")
        object.__setattr__(
            self, "specification", text(self.specification, "specification", maximum=500)
        )


@dataclass(frozen=True, slots=True)
class SupplierQuoteLine:
    rfq_item_id: UUID
    offered_quantity: Decimal
    unit_price: Decimal
    lead_time_days: int

    def __post_init__(self) -> None:
        require_uuid(self.rfq_item_id, "rfq_item_id")
        object.__setattr__(self, "offered_quantity", quantity(self.offered_quantity))
        normalized_price = money(self.unit_price, "unit_price")
        if normalized_price <= 0:
            raise InvalidRequestForQuotationError("unit_price must be positive.")
        object.__setattr__(self, "unit_price", normalized_price)
        if (
            not isinstance(self.lead_time_days, int)
            or isinstance(self.lead_time_days, bool)
            or self.lead_time_days < 0
        ):
            raise InvalidRequestForQuotationError("lead_time_days must be a non-negative integer.")

    @property
    def line_total(self) -> Decimal:
        return (self.offered_quantity * self.unit_price).quantize(Decimal("0.01"))


@dataclass(frozen=True, slots=True)
class SupplierQuote:
    id: UUID
    supplier_id: UUID
    currency: str
    submitted_at: datetime
    valid_until: date
    lines: tuple[SupplierQuoteLine, ...]
    freight_amount: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        require_uuid(self.id, "id")
        require_uuid(self.supplier_id, "supplier_id")
        object.__setattr__(self, "currency", currency(self.currency))
        _aware(self.submitted_at, "submitted_at")
        if not isinstance(self.valid_until, date) or self.valid_until < self.submitted_at.date():
            raise InvalidRequestForQuotationError("valid_until cannot predate submission.")
        if not isinstance(self.lines, tuple) or not self.lines:
            raise InvalidRequestForQuotationError("Supplier quote must contain lines.")
        if any(not isinstance(line, SupplierQuoteLine) for line in self.lines):
            raise InvalidRequestForQuotationError("lines must contain SupplierQuoteLine values.")
        identities = [line.rfq_item_id for line in self.lines]
        if len(identities) != len(set(identities)):
            raise InvalidRequestForQuotationError("Supplier quote cannot repeat an RFQ item.")
        object.__setattr__(self, "freight_amount", money(self.freight_amount, "freight_amount"))

    @property
    def total_amount(self) -> Decimal:
        return sum((line.line_total for line in self.lines), self.freight_amount).quantize(
            Decimal("0.01")
        )


@dataclass(frozen=True, slots=True)
class QuotationAward:
    quote_id: UUID
    supplier_id: UUID
    awarded_by: UUID
    awarded_at: datetime

    def __post_init__(self) -> None:
        for field in ("quote_id", "supplier_id", "awarded_by"):
            require_uuid(getattr(self, field), field)
        _aware(self.awarded_at, "awarded_at")


@dataclass(frozen=True, slots=True)
class RequestForQuotation:
    id: UUID
    company_id: UUID
    code: str
    created_by: UUID
    response_deadline: date
    items: tuple[RequestForQuotationItem, ...]
    invited_supplier_ids: tuple[UUID, ...]
    status: RequestForQuotationStatus = RequestForQuotationStatus.DRAFT
    supplier_quotes: tuple[SupplierQuote, ...] = ()
    version: int = 1
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    award: QuotationAward | None = None
    cancellation_reason: str | None = None

    def __post_init__(self) -> None:
        for field in ("id", "company_id", "created_by"):
            require_uuid(getattr(self, field), field)
        object.__setattr__(self, "code", identifier(self.code, "code", maximum=40))
        if not isinstance(self.response_deadline, date):
            raise InvalidRequestForQuotationError("response_deadline must be a date.")
        if not isinstance(self.items, tuple) or not self.items:
            raise InvalidRequestForQuotationError("RFQ must contain items.")
        if any(not isinstance(item, RequestForQuotationItem) for item in self.items):
            raise InvalidRequestForQuotationError("items must contain RFQ items.")
        item_ids = [item.id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise InvalidRequestForQuotationError("RFQ item identities must be unique.")
        if not isinstance(self.invited_supplier_ids, tuple) or not self.invited_supplier_ids:
            raise InvalidRequestForQuotationError("RFQ must invite at least one supplier.")
        for supplier_id in self.invited_supplier_ids:
            require_uuid(supplier_id, "supplier_id")
        if len(self.invited_supplier_ids) != len(set(self.invited_supplier_ids)):
            raise InvalidRequestForQuotationError("Invited suppliers must be unique.")
        if not isinstance(self.status, RequestForQuotationStatus):
            raise InvalidRequestForQuotationError("status must be an RFQ status.")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise InvalidRequestForQuotationError("version must be a positive integer.")
        self._validate_evidence()

    def open(self, *, occurred_at: datetime) -> RequestForQuotation:
        self._require(RequestForQuotationStatus.DRAFT)
        return replace(
            self,
            status=RequestForQuotationStatus.OPEN,
            opened_at=_aware(occurred_at, "occurred_at"),
            version=self.version + 1,
        )

    def record_quote(self, quote: SupplierQuote) -> RequestForQuotation:
        self._require(RequestForQuotationStatus.OPEN)
        self._validate_quote(quote)
        if any(value.supplier_id == quote.supplier_id for value in self.supplier_quotes):
            raise InvalidRequestForQuotationError("Supplier already submitted a quote.")
        return replace(
            self,
            supplier_quotes=(*self.supplier_quotes, quote),
            version=self.version + 1,
        )

    def close(self, *, occurred_at: datetime) -> RequestForQuotation:
        self._require(RequestForQuotationStatus.OPEN)
        if not self.supplier_quotes:
            raise InvalidRequestForQuotationError("RFQ cannot close without supplier quotes.")
        instant = _aware(occurred_at, "occurred_at")
        assert self.opened_at is not None
        if instant < self.opened_at:
            raise InvalidRequestForQuotationError("closed_at cannot predate opened_at.")
        return replace(
            self,
            status=RequestForQuotationStatus.CLOSED,
            closed_at=instant,
            version=self.version + 1,
        )

    def award_quote(
        self,
        *,
        quote_id: UUID,
        actor_id: UUID,
        occurred_at: datetime,
    ) -> RequestForQuotation:
        self._require(RequestForQuotationStatus.CLOSED)
        actor = require_uuid(actor_id, "actor_id")
        if actor == self.created_by:
            raise RequestForQuotationSodViolationError(
                "RFQ creator cannot award the same competition."
            )
        selected = next((quote for quote in self.supplier_quotes if quote.id == quote_id), None)
        if selected is None:
            raise InvalidRequestForQuotationError("Selected supplier quote does not exist.")
        instant = _aware(occurred_at, "occurred_at")
        if selected.valid_until < instant.date():
            raise InvalidRequestForQuotationError("Selected supplier quote is expired.")
        return replace(
            self,
            status=RequestForQuotationStatus.AWARDED,
            award=QuotationAward(selected.id, selected.supplier_id, actor, instant),
            version=self.version + 1,
        )

    def cancel(self, *, reason: str) -> RequestForQuotation:
        if self.status not in {
            RequestForQuotationStatus.DRAFT,
            RequestForQuotationStatus.OPEN,
            RequestForQuotationStatus.CLOSED,
        }:
            raise InvalidRequestForQuotationTransitionError(
                "RFQ cannot be cancelled in this state."
            )
        return replace(
            self,
            status=RequestForQuotationStatus.CANCELLED,
            cancellation_reason=text(reason, "reason", maximum=500),
            version=self.version + 1,
        )

    def _require(self, status: RequestForQuotationStatus) -> None:
        if self.status is not status:
            raise InvalidRequestForQuotationTransitionError(
                f"RFQ must be {status.value}, not {self.status.value}."
            )

    def _validate_evidence(self) -> None:
        if self.opened_at is not None:
            _aware(self.opened_at, "opened_at")
        if self.closed_at is not None:
            _aware(self.closed_at, "closed_at")
        if any(not isinstance(quote, SupplierQuote) for quote in self.supplier_quotes):
            raise InvalidRequestForQuotationError(
                "supplier_quotes must contain SupplierQuote values."
            )
        for quote in self.supplier_quotes:
            self._validate_quote(quote)
        quote_suppliers = [quote.supplier_id for quote in self.supplier_quotes]
        if len(quote_suppliers) != len(set(quote_suppliers)):
            raise InvalidRequestForQuotationError("A supplier can quote an RFQ only once.")
        if self.status is RequestForQuotationStatus.DRAFT and (
            self.opened_at is not None or self.supplier_quotes
        ):
            raise InvalidRequestForQuotationError("Draft RFQ cannot contain execution evidence.")
        if (
            self.status
            in {
                RequestForQuotationStatus.OPEN,
                RequestForQuotationStatus.CLOSED,
                RequestForQuotationStatus.AWARDED,
            }
            and self.opened_at is None
        ):
            raise InvalidRequestForQuotationError("Opened RFQ states require opened_at.")
        if (
            self.status
            in {
                RequestForQuotationStatus.CLOSED,
                RequestForQuotationStatus.AWARDED,
            }
            and self.closed_at is None
        ):
            raise InvalidRequestForQuotationError("Closed RFQ states require closed_at.")
        if (
            self.opened_at is not None
            and self.closed_at is not None
            and self.closed_at < self.opened_at
        ):
            raise InvalidRequestForQuotationError("closed_at cannot predate opened_at.")
        if (self.status is RequestForQuotationStatus.AWARDED) != (self.award is not None):
            raise InvalidRequestForQuotationError("Award evidence is exclusive to awarded RFQs.")
        if self.award is not None:
            if not isinstance(self.award, QuotationAward):
                raise InvalidRequestForQuotationError("award must be a QuotationAward.")
            selected = next(
                (quote for quote in self.supplier_quotes if quote.id == self.award.quote_id),
                None,
            )
            if selected is None or selected.supplier_id != self.award.supplier_id:
                raise InvalidRequestForQuotationError("Award must reference a submitted quote.")
            if self.closed_at is not None and self.award.awarded_at < self.closed_at:
                raise InvalidRequestForQuotationError("Award cannot predate RFQ closure.")
        if (self.status is RequestForQuotationStatus.CANCELLED) != (
            self.cancellation_reason is not None
        ):
            raise InvalidRequestForQuotationError(
                "Cancellation reason is exclusive to cancelled RFQs."
            )
        if self.cancellation_reason is not None:
            object.__setattr__(
                self,
                "cancellation_reason",
                text(self.cancellation_reason, "cancellation_reason", maximum=500),
            )

    def _validate_quote(self, quote: SupplierQuote) -> None:
        if not isinstance(quote, SupplierQuote):
            raise InvalidRequestForQuotationError("quote must be a SupplierQuote.")
        if quote.supplier_id not in self.invited_supplier_ids:
            raise InvalidRequestForQuotationError("Supplier was not invited to this RFQ.")
        if quote.submitted_at.date() > self.response_deadline:
            raise InvalidRequestForQuotationError("Supplier quote arrived after the deadline.")
        expected = {item.id: item for item in self.items}
        if {line.rfq_item_id for line in quote.lines} != set(expected):
            raise InvalidRequestForQuotationError("Supplier quote must cover every RFQ item once.")
        if any(line.offered_quantity < expected[line.rfq_item_id].quantity for line in quote.lines):
            raise InvalidRequestForQuotationError(
                "Supplier quote cannot offer less than requested."
            )


__all__ = [
    "QuotationAward",
    "RequestForQuotation",
    "RequestForQuotationItem",
    "RequestForQuotationStatus",
    "SupplierQuote",
    "SupplierQuoteLine",
]
