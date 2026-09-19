"""M15 sales-quote aggregate and immutable commercial revisions."""

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.sales.domain.support import identifier, money, quantity, require_uuid


class SalesQuoteStatus(StrEnum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    LOST = "LOST"
    CONVERTED = "CONVERTED"


@dataclass(frozen=True, slots=True)
class QuoteRevisionItem:
    id: UUID
    company_id: UUID
    revision_id: UUID
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        revision_id: UUID,
        product_id: UUID,
        quantity_value: Decimal | str | int,
        unit_price: Decimal | str | int,
        discount_amount: Decimal | str | int = Decimal("0"),
    ) -> QuoteRevisionItem:
        item = cls(
            id=uuid4(),
            company_id=require_uuid(company_id, "company_id"),
            revision_id=require_uuid(revision_id, "revision_id"),
            product_id=require_uuid(product_id, "product_id"),
            quantity=quantity(quantity_value),
            unit_price=money(unit_price, "unit_price"),
            discount_amount=money(discount_amount, "discount_amount"),
        )
        if item.discount_amount > item.gross_amount:
            raise ValueError("discount_amount cannot exceed gross amount.")
        return item

    @property
    def gross_amount(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"))

    @property
    def net_amount(self) -> Decimal:
        return self.gross_amount - self.discount_amount


@dataclass(frozen=True, slots=True)
class QuoteRevision:
    id: UUID
    company_id: UUID
    quote_id: UUID
    revision_number: int
    items: tuple[QuoteRevisionItem, ...]
    gross_amount: Decimal
    discount_amount: Decimal
    net_amount: Decimal
    pricing_snapshot_refs: tuple[UUID, ...]

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        quote_id: UUID,
        revision_number: int,
        lines: tuple[tuple[UUID, Decimal | str | int, Decimal | str | int, Decimal | str | int], ...],
        pricing_snapshot_refs: tuple[UUID, ...] = (),
    ) -> QuoteRevision:
        if type(revision_number) is not int or revision_number < 1:
            raise ValueError("revision_number must be a positive integer.")
        if not lines:
            raise ValueError("quote revision requires at least one item.")
        revision_id = uuid4()
        items = tuple(
            QuoteRevisionItem.create(
                company_id=company_id,
                revision_id=revision_id,
                product_id=product_id,
                quantity_value=item_quantity,
                unit_price=unit_price,
                discount_amount=discount,
            )
            for product_id, item_quantity, unit_price, discount in lines
        )
        if len({item.product_id for item in items}) != len(items):
            raise ValueError("a product can appear only once in a quote revision.")
        gross = sum((item.gross_amount for item in items), Decimal("0.00"))
        discount = sum((item.discount_amount for item in items), Decimal("0.00"))
        snapshots = tuple(
            require_uuid(value, "pricing_snapshot_ref") for value in pricing_snapshot_refs
        )
        if snapshots and len(snapshots) != len(items):
            raise ValueError("pricing snapshot references must match quote items.")
        return cls(
            id=revision_id,
            company_id=require_uuid(company_id, "company_id"),
            quote_id=require_uuid(quote_id, "quote_id"),
            revision_number=revision_number,
            items=items,
            gross_amount=gross,
            discount_amount=discount,
            net_amount=gross - discount,
            pricing_snapshot_refs=snapshots,
        )


@dataclass(frozen=True, slots=True)
class SalesQuote:
    id: UUID
    company_id: UUID
    number: str
    customer_id: UUID
    seller_id: UUID
    currency: str
    status: SalesQuoteStatus
    current_revision_number: int
    workflow_instance_id: UUID | None
    converted_order_id: UUID | None
    version: int

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        number: str,
        customer_id: UUID,
        seller_id: UUID,
        currency: str = "BRL",
    ) -> SalesQuote:
        normalized_currency = currency.strip().upper()
        if normalized_currency != "BRL":
            raise ValueError("M15 initial slice supports BRL only.")
        return cls(
            id=uuid4(),
            company_id=require_uuid(company_id, "company_id"),
            number=identifier(number, "number"),
            customer_id=require_uuid(customer_id, "customer_id"),
            seller_id=require_uuid(seller_id, "seller_id"),
            currency=normalized_currency,
            status=SalesQuoteStatus.DRAFT,
            current_revision_number=0,
            workflow_instance_id=None,
            converted_order_id=None,
            version=1,
        )

    def revise(
        self,
        *,
        lines: tuple[tuple[UUID, Decimal | str | int, Decimal | str | int, Decimal | str | int], ...],
        pricing_snapshot_refs: tuple[UUID, ...] = (),
    ) -> tuple[SalesQuote, QuoteRevision]:
        if self.status is not SalesQuoteStatus.DRAFT:
            raise ValueError("only draft quotes can receive a new revision.")
        revision = QuoteRevision.create(
            company_id=self.company_id,
            quote_id=self.id,
            revision_number=self.current_revision_number + 1,
            lines=lines,
            pricing_snapshot_refs=pricing_snapshot_refs,
        )
        return (
            replace(
                self,
                current_revision_number=revision.revision_number,
                version=self.version + 1,
            ),
            revision,
        )

    def send(self) -> SalesQuote:
        if self.status is not SalesQuoteStatus.DRAFT or self.current_revision_number < 1:
            raise ValueError("only a revised draft quote can be sent.")
        return replace(self, status=SalesQuoteStatus.SENT, version=self.version + 1)

    def accept(self, *, partial: bool = False) -> SalesQuote:
        if self.status is not SalesQuoteStatus.SENT:
            raise ValueError("only sent quotes can be accepted.")
        status = (
            SalesQuoteStatus.PARTIALLY_ACCEPTED if partial else SalesQuoteStatus.ACCEPTED
        )
        return replace(self, status=status, version=self.version + 1)

    def mark_lost(self) -> SalesQuote:
        if self.status not in {SalesQuoteStatus.DRAFT, SalesQuoteStatus.SENT}:
            raise ValueError("only draft or sent quotes can be marked lost.")
        return replace(self, status=SalesQuoteStatus.LOST, version=self.version + 1)

    def convert(self, order_id: UUID) -> SalesQuote:
        if self.status not in {
            SalesQuoteStatus.ACCEPTED,
            SalesQuoteStatus.PARTIALLY_ACCEPTED,
        }:
            raise ValueError("only accepted quotes can be converted.")
        return replace(
            self,
            status=SalesQuoteStatus.CONVERTED,
            converted_order_id=require_uuid(order_id, "order_id"),
            version=self.version + 1,
        )


__all__ = [
    "QuoteRevision",
    "QuoteRevisionItem",
    "SalesQuote",
    "SalesQuoteStatus",
]
