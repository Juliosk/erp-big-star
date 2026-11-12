"""Tenant-bound persistence adapter for the M6 RFQ aggregate."""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.procurement.domain import (
    InvalidRequestForQuotationError,
    QuotationAward,
    RequestForQuotation,
    RequestForQuotationConflictError,
    RequestForQuotationItem,
    RequestForQuotationScopeError,
    RequestForQuotationStatus,
    RequestForQuotationVersionConflictError,
    SupplierQuote,
    SupplierQuoteLine,
)
from erp.modules.procurement.infrastructure.rfq_model import (
    RequestForQuotationItemModel,
    RequestForQuotationModel,
    RequestForQuotationQuoteLineModel,
    RequestForQuotationSupplierModel,
)


class RequestForQuotationRepository:
    """Persist RFQs and immutable supplier quotes without transaction ownership."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID) or company_id.int == 0:
            raise ValueError("An explicit non-zero company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, rfq: RequestForQuotation, *, actor_id: UUID) -> None:
        self._write_scope(rfq, actor_id)
        if rfq.version != 1 or rfq.status is not RequestForQuotationStatus.DRAFT:
            raise ValueError("A new RFQ must start draft at version one.")
        if rfq.supplier_quotes:
            raise ValueError("A new RFQ cannot already contain supplier quotes.")
        now = datetime.now(UTC)
        root = RequestForQuotationModel(
            id=rfq.id,
            company_id=rfq.company_id,
            code=rfq.code,
            created_by=rfq.created_by,
            response_deadline=rfq.response_deadline,
            created_at=now,
            **_root_values(rfq, actor_id=actor_id, occurred_at=now),
        )
        self._session.add(root)
        # The aggregate uses composite tenant-bound foreign keys without ORM
        # relationships.  Flush the root first so PostgreSQL can enforce those
        # keys while transaction ownership remains with the application layer.
        await self._flush()
        self._session.add_all(
            RequestForQuotationItemModel(
                id=item.id,
                company_id=rfq.company_id,
                rfq_id=rfq.id,
                item_sequence=sequence,
                product_id=item.product_id,
                quantity=item.quantity,
                uom=item.uom,
                required_on=item.required_on,
                specification=item.specification,
                created_by=actor_id,
            )
            for sequence, item in enumerate(rfq.items, start=1)
        )
        self._session.add_all(
            RequestForQuotationSupplierModel(
                company_id=rfq.company_id,
                rfq_id=rfq.id,
                supplier_id=supplier_id,
                invitation_sequence=sequence,
                quote_id=None,
                quote_sequence=None,
                currency=None,
                submitted_at=None,
                valid_until=None,
                freight_amount=None,
                created_by=actor_id,
                updated_by=actor_id,
            )
            for sequence, supplier_id in enumerate(rfq.invited_supplier_ids, start=1)
        )
        await self._flush()

    async def get(self, rfq_id: UUID) -> RequestForQuotation | None:
        root = await self._session.scalar(
            select(RequestForQuotationModel)
            .where(
                RequestForQuotationModel.company_id == self._company_id,
                RequestForQuotationModel.id == rfq_id,
            )
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return await self._aggregate(root)

    async def get_for_update(self, rfq_id: UUID) -> RequestForQuotation | None:
        root = await self._session.scalar(
            select(RequestForQuotationModel)
            .where(
                RequestForQuotationModel.company_id == self._company_id,
                RequestForQuotationModel.id == rfq_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if root is None:
            return None
        return await self._aggregate(root)

    async def list(
        self,
        *,
        status: RequestForQuotationStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[RequestForQuotation, ...]:
        _page(limit, offset)
        statement = select(RequestForQuotationModel).where(
            RequestForQuotationModel.company_id == self._company_id
        )
        if status is not None:
            if not isinstance(status, RequestForQuotationStatus):
                raise ValueError("status must be an official RFQ status.")
            statement = statement.where(RequestForQuotationModel.status == status.value)
        roots = await self._session.scalars(
            statement.order_by(
                RequestForQuotationModel.response_deadline,
                RequestForQuotationModel.code,
                RequestForQuotationModel.id,
            )
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple([await self._aggregate(root) for root in roots])

    async def save(
        self,
        rfq: RequestForQuotation,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> RequestForQuotation:
        self._write_scope(rfq, actor_id)
        compare = rfq.version - 1 if expected_version is None else expected_version
        if compare < 1 or rfq.version != compare + 1:
            raise ValueError("save requires exactly one aggregate version increment.")
        current = await self.get(rfq.id)
        if current is None or current.version != compare:
            raise RequestForQuotationVersionConflictError(
                f"RFQ expected version {compare} is stale."
            )
        _validate_frozen_state(current, rfq)
        new_quotes = _validate_transition(current, rfq)
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(RequestForQuotationModel)
                .where(
                    RequestForQuotationModel.company_id == self._company_id,
                    RequestForQuotationModel.id == rfq.id,
                    RequestForQuotationModel.version == compare,
                )
                .values(
                    **_root_values(
                        rfq,
                        actor_id=actor_id,
                        occurred_at=datetime.now(UTC),
                    )
                )
            ),
        )
        if result.rowcount != 1:
            raise RequestForQuotationVersionConflictError(
                f"RFQ expected version {compare} is stale."
            )
        for quote in new_quotes:
            await self._persist_quote(
                rfq,
                quote,
                actor_id=actor_id,
                sequence=rfq.supplier_quotes.index(quote) + 1,
            )
        await self._flush()
        return rfq

    async def _persist_quote(
        self,
        rfq: RequestForQuotation,
        quote: SupplierQuote,
        *,
        actor_id: UUID,
        sequence: int,
    ) -> None:
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(RequestForQuotationSupplierModel)
                .where(
                    RequestForQuotationSupplierModel.company_id == self._company_id,
                    RequestForQuotationSupplierModel.rfq_id == rfq.id,
                    RequestForQuotationSupplierModel.supplier_id == quote.supplier_id,
                    RequestForQuotationSupplierModel.quote_id.is_(None),
                )
                .values(
                    quote_id=quote.id,
                    quote_sequence=sequence,
                    currency=quote.currency,
                    submitted_at=quote.submitted_at,
                    valid_until=quote.valid_until,
                    freight_amount=quote.freight_amount,
                    updated_by=actor_id,
                )
            ),
        )
        if result.rowcount != 1:
            raise RequestForQuotationVersionConflictError(
                "Supplier quote was already recorded or invitation is stale."
            )
        self._session.add_all(
            RequestForQuotationQuoteLineModel(
                company_id=rfq.company_id,
                rfq_id=rfq.id,
                supplier_id=quote.supplier_id,
                rfq_item_id=line.rfq_item_id,
                offered_quantity=line.offered_quantity,
                unit_price=line.unit_price,
                lead_time_days=line.lead_time_days,
            )
            for line in quote.lines
        )

    async def _aggregate(self, root: RequestForQuotationModel) -> RequestForQuotation:
        items = tuple(
            await self._session.scalars(
                select(RequestForQuotationItemModel)
                .where(
                    RequestForQuotationItemModel.company_id == self._company_id,
                    RequestForQuotationItemModel.rfq_id == root.id,
                )
                .order_by(RequestForQuotationItemModel.item_sequence)
                .execution_options(populate_existing=True)
            )
        )
        suppliers = tuple(
            await self._session.scalars(
                select(RequestForQuotationSupplierModel)
                .where(
                    RequestForQuotationSupplierModel.company_id == self._company_id,
                    RequestForQuotationSupplierModel.rfq_id == root.id,
                )
                .order_by(RequestForQuotationSupplierModel.invitation_sequence)
                .execution_options(populate_existing=True)
            )
        )
        lines = tuple(
            await self._session.scalars(
                select(RequestForQuotationQuoteLineModel)
                .where(
                    RequestForQuotationQuoteLineModel.company_id == self._company_id,
                    RequestForQuotationQuoteLineModel.rfq_id == root.id,
                )
                .execution_options(populate_existing=True)
            )
        )
        return _rfq(root, items, suppliers, lines)

    def _write_scope(self, rfq: RequestForQuotation, actor_id: UUID) -> None:
        if not isinstance(rfq, RequestForQuotation):
            raise TypeError("rfq must be a RequestForQuotation.")
        if rfq.company_id != self._company_id:
            raise RequestForQuotationScopeError("RFQ is outside the selected company.")
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise ValueError("An explicit non-zero actor UUID is required.")

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise RequestForQuotationConflictError(
                    "RFQ code, quote identity or sequence already exists for this company."
                ) from error
            raise


def _root_values(
    rfq: RequestForQuotation,
    *,
    actor_id: UUID,
    occurred_at: datetime,
) -> dict[str, Any]:
    award = rfq.award
    return {
        "status": rfq.status.value,
        "opened_at": rfq.opened_at,
        "closed_at": rfq.closed_at,
        "awarded_quote_id": award.quote_id if award else None,
        "awarded_supplier_id": award.supplier_id if award else None,
        "awarded_by": award.awarded_by if award else None,
        "awarded_at": award.awarded_at if award else None,
        "cancellation_reason": rfq.cancellation_reason,
        "version": rfq.version,
        "updated_at": occurred_at,
        "updated_by": actor_id,
    }


def _rfq(
    root: RequestForQuotationModel,
    items: tuple[RequestForQuotationItemModel, ...],
    suppliers: tuple[RequestForQuotationSupplierModel, ...],
    lines: tuple[RequestForQuotationQuoteLineModel, ...],
) -> RequestForQuotation:
    line_map: dict[UUID, dict[UUID, RequestForQuotationQuoteLineModel]] = defaultdict(dict)
    for line in lines:
        line_map[line.supplier_id][line.rfq_item_id] = line
    domain_items = tuple(
        RequestForQuotationItem(
            id=item.id,
            product_id=item.product_id,
            quantity=item.quantity,
            uom=item.uom,
            required_on=item.required_on,
            specification=item.specification,
        )
        for item in items
    )
    quoted_suppliers = sorted(
        (supplier for supplier in suppliers if supplier.quote_id is not None),
        key=lambda supplier: cast(int, supplier.quote_sequence),
    )
    quotes = tuple(
        _quote(supplier, items, line_map[supplier.supplier_id]) for supplier in quoted_suppliers
    )
    return RequestForQuotation(
        id=root.id,
        company_id=root.company_id,
        code=root.code,
        created_by=root.created_by,
        response_deadline=root.response_deadline,
        items=domain_items,
        invited_supplier_ids=tuple(supplier.supplier_id for supplier in suppliers),
        status=RequestForQuotationStatus(root.status),
        supplier_quotes=quotes,
        version=root.version,
        opened_at=root.opened_at,
        closed_at=root.closed_at,
        award=_award(root),
        cancellation_reason=root.cancellation_reason,
    )


def _quote(
    supplier: RequestForQuotationSupplierModel,
    items: tuple[RequestForQuotationItemModel, ...],
    lines: dict[UUID, RequestForQuotationQuoteLineModel],
) -> SupplierQuote:
    if (
        supplier.quote_id is None
        or supplier.currency is None
        or supplier.submitted_at is None
        or supplier.valid_until is None
        or supplier.freight_amount is None
    ):
        raise InvalidRequestForQuotationError("Persisted supplier quote is incomplete.")
    return SupplierQuote(
        id=supplier.quote_id,
        supplier_id=supplier.supplier_id,
        currency=supplier.currency,
        submitted_at=supplier.submitted_at,
        valid_until=supplier.valid_until,
        lines=tuple(
            SupplierQuoteLine(
                rfq_item_id=item.id,
                offered_quantity=lines[item.id].offered_quantity,
                unit_price=lines[item.id].unit_price,
                lead_time_days=lines[item.id].lead_time_days,
            )
            for item in items
        ),
        freight_amount=supplier.freight_amount,
    )


def _award(root: RequestForQuotationModel) -> QuotationAward | None:
    values = (
        root.awarded_quote_id,
        root.awarded_supplier_id,
        root.awarded_by,
        root.awarded_at,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise InvalidRequestForQuotationError("Persisted RFQ award is incomplete.")
    return QuotationAward(
        cast(UUID, root.awarded_quote_id),
        cast(UUID, root.awarded_supplier_id),
        cast(UUID, root.awarded_by),
        cast(datetime, root.awarded_at),
    )


def _validate_frozen_state(
    current: RequestForQuotation,
    candidate: RequestForQuotation,
) -> None:
    if (
        current.company_id != candidate.company_id
        or current.code != candidate.code
        or current.created_by != candidate.created_by
        or current.response_deadline != candidate.response_deadline
        or current.items != candidate.items
        or current.invited_supplier_ids != candidate.invited_supplier_ids
        or candidate.supplier_quotes[: len(current.supplier_quotes)] != current.supplier_quotes
    ):
        raise InvalidRequestForQuotationError(
            "RFQ identity, demand, invitations and recorded quotes are immutable."
        )


def _validate_transition(
    current: RequestForQuotation,
    candidate: RequestForQuotation,
) -> tuple[SupplierQuote, ...]:
    new_quotes = candidate.supplier_quotes[len(current.supplier_quotes) :]
    if current.status is RequestForQuotationStatus.OPEN and candidate.status is current.status:
        if len(new_quotes) != 1:
            raise InvalidRequestForQuotationError(
                "Recording a quote must append exactly one quote."
            )
        return new_quotes
    allowed = {
        RequestForQuotationStatus.DRAFT: {
            RequestForQuotationStatus.OPEN,
            RequestForQuotationStatus.CANCELLED,
        },
        RequestForQuotationStatus.OPEN: {
            RequestForQuotationStatus.CLOSED,
            RequestForQuotationStatus.CANCELLED,
        },
        RequestForQuotationStatus.CLOSED: {
            RequestForQuotationStatus.AWARDED,
            RequestForQuotationStatus.CANCELLED,
        },
    }
    if candidate.status not in allowed.get(current.status, set()) or new_quotes:
        raise InvalidRequestForQuotationError(
            f"Persistence transition {current.status.value} -> {candidate.status.value} "
            "is not allowed."
        )
    return ()


def _page(limit: int, offset: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer.")


__all__ = ["RequestForQuotationRepository"]
