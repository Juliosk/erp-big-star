"""Pure M4 Sales Order aggregate created from accepted commercial quotes."""

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.sales.domain.support import identifier, money, quantity, require_uuid


class SalesOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class SalesOrderItem:
    id: UUID
    company_id: UUID
    order_id: UUID
    quote_revision_item_id: UUID
    product_id: UUID
    quantity: Decimal
    unit_price: Decimal
    discount_amount: Decimal
    pricing_snapshot_id: UUID | None

    @classmethod
    def create(
        cls,
        *,
        company_id: UUID,
        order_id: UUID,
        quote_revision_item_id: UUID,
        product_id: UUID,
        quantity_value: Decimal | str | int,
        unit_price: Decimal | str | int,
        discount_amount: Decimal | str | int,
        pricing_snapshot_id: UUID | None,
    ) -> SalesOrderItem:
        item = cls(
            id=uuid4(),
            company_id=require_uuid(company_id, "company_id"),
            order_id=require_uuid(order_id, "order_id"),
            quote_revision_item_id=require_uuid(
                quote_revision_item_id, "quote_revision_item_id"
            ),
            product_id=require_uuid(product_id, "product_id"),
            quantity=quantity(quantity_value),
            unit_price=money(unit_price, "unit_price"),
            discount_amount=money(discount_amount, "discount_amount"),
            pricing_snapshot_id=(
                require_uuid(pricing_snapshot_id, "pricing_snapshot_id")
                if pricing_snapshot_id is not None
                else None
            ),
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
class SalesOrder:
    id: UUID
    company_id: UUID
    number: str
    source_quote_id: UUID
    source_quote_revision_number: int
    customer_id: UUID
    seller_id: UUID
    currency: str
    status: SalesOrderStatus
    items: tuple[SalesOrderItem, ...]
    gross_amount: Decimal
    discount_amount: Decimal
    net_amount: Decimal
    version: int

    @classmethod
    def create_from_quote(
        cls,
        *,
        company_id: UUID,
        number: str,
        source_quote_id: UUID,
        source_quote_revision_number: int,
        customer_id: UUID,
        seller_id: UUID,
        currency: str,
        lines: tuple[
            tuple[UUID, UUID, Decimal | str | int, Decimal | str | int, Decimal | str | int, UUID | None],
            ...,
        ],
    ) -> SalesOrder:
        if type(source_quote_revision_number) is not int or source_quote_revision_number < 1:
            raise ValueError("source_quote_revision_number must be positive.")
        normalized_currency = currency.strip().upper()
        if normalized_currency != "BRL":
            raise ValueError("M4 initial slice supports BRL only.")
        if not lines:
            raise ValueError("sales order requires at least one item.")
        order_id = uuid4()
        items = tuple(
            SalesOrderItem.create(
                company_id=company_id,
                order_id=order_id,
                quote_revision_item_id=revision_item_id,
                product_id=product_id,
                quantity_value=item_quantity,
                unit_price=unit_price,
                discount_amount=discount,
                pricing_snapshot_id=snapshot_id,
            )
            for revision_item_id, product_id, item_quantity, unit_price, discount, snapshot_id in lines
        )
        if len({item.product_id for item in items}) != len(items):
            raise ValueError("a product can appear only once in a sales order.")
        gross = sum((item.gross_amount for item in items), Decimal("0.00"))
        discount = sum((item.discount_amount for item in items), Decimal("0.00"))
        return cls(
            id=order_id,
            company_id=require_uuid(company_id, "company_id"),
            number=identifier(number, "number"),
            source_quote_id=require_uuid(source_quote_id, "source_quote_id"),
            source_quote_revision_number=source_quote_revision_number,
            customer_id=require_uuid(customer_id, "customer_id"),
            seller_id=require_uuid(seller_id, "seller_id"),
            currency=normalized_currency,
            status=SalesOrderStatus.DRAFT,
            items=items,
            gross_amount=gross,
            discount_amount=discount,
            net_amount=gross - discount,
            version=1,
        )

    def approve(self) -> SalesOrder:
        if self.status is not SalesOrderStatus.DRAFT:
            raise ValueError("only draft orders can be approved.")
        return replace(self, status=SalesOrderStatus.APPROVED, version=self.version + 1)

    def cancel(self) -> SalesOrder:
        if self.status not in {SalesOrderStatus.DRAFT, SalesOrderStatus.APPROVED}:
            raise ValueError("only draft or approved orders can be cancelled.")
        return replace(self, status=SalesOrderStatus.CANCELLED, version=self.version + 1)

    def complete(self) -> SalesOrder:
        if self.status is not SalesOrderStatus.APPROVED:
            raise ValueError("only approved orders can be completed.")
        return replace(self, status=SalesOrderStatus.COMPLETED, version=self.version + 1)


__all__ = ["SalesOrder", "SalesOrderItem", "SalesOrderStatus"]
