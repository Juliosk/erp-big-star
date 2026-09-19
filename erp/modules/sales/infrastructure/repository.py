"""Tenant-bound PostgreSQL repository for the M15 quote aggregate."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.sales.domain import (
    QuoteRevision,
    QuoteRevisionItem,
    SalesQuote,
    SalesQuoteStatus,
)
from erp.modules.sales.infrastructure.quote_model import (
    QuoteRevisionItemModel,
    QuoteRevisionModel,
    SalesQuoteModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


def _quote(model: SalesQuoteModel) -> SalesQuote:
    return SalesQuote(
        id=model.id,
        company_id=model.company_id,
        number=model.number,
        customer_id=model.customer_id,
        seller_id=model.seller_id,
        currency=model.currency,
        status=SalesQuoteStatus(model.status),
        current_revision_number=model.current_revision_number,
        workflow_instance_id=model.workflow_instance_id,
        converted_order_id=model.converted_order_id,
        version=model.version,
    )


def _revision(
    model: QuoteRevisionModel, items: tuple[QuoteRevisionItemModel, ...]
) -> QuoteRevision:
    domain_items = tuple(
        QuoteRevisionItem(
            id=item.id,
            company_id=item.company_id,
            revision_id=item.revision_id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=item.unit_price,
            discount_amount=item.discount_amount,
        )
        for item in items
    )
    return QuoteRevision(
        id=model.id,
        company_id=model.company_id,
        quote_id=model.quote_id,
        revision_number=model.revision_number,
        items=domain_items,
        gross_amount=model.gross_amount,
        discount_amount=model.discount_amount,
        net_amount=model.net_amount,
        pricing_snapshot_refs=tuple(
            item.pricing_snapshot_id
            for item in items
            if item.pricing_snapshot_id is not None
        ),
    )


class SalesQuoteRepository:
    """Persist quotes without ever exposing an unscoped operation."""

    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        if not isinstance(company_id, UUID):
            raise ValueError("An explicit company UUID is required.")
        self._session = session
        self._company_id = company_id

    async def add(self, quote: SalesQuote, *, actor_id: UUID) -> None:
        self._validate_write(quote.company_id, actor_id)
        if (
            quote.version != 1
            or quote.status is not SalesQuoteStatus.DRAFT
            or quote.current_revision_number != 0
        ):
            raise ValueError("A new quote must be an unrevised draft at version one.")
        self._session.add(
            SalesQuoteModel(
                id=quote.id,
                company_id=self._company_id,
                number=quote.number,
                customer_id=quote.customer_id,
                seller_id=quote.seller_id,
                currency=quote.currency,
                status=quote.status,
                current_revision_number=0,
                workflow_instance_id=None,
                converted_order_id=None,
                version=1,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await self._flush_conflict()

    async def get(self, quote_id: UUID) -> SalesQuote | None:
        result = await self._session.scalars(
            select(SalesQuoteModel)
            .where(
                SalesQuoteModel.company_id == self._company_id,
                SalesQuoteModel.id == quote_id,
            )
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _quote(model)

    async def get_for_update(self, quote_id: UUID) -> SalesQuote | None:
        result = await self._session.scalars(
            select(SalesQuoteModel)
            .where(
                SalesQuoteModel.company_id == self._company_id,
                SalesQuoteModel.id == quote_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        model = result.one_or_none()
        return None if model is None else _quote(model)

    async def list(
        self,
        *,
        status: SalesQuoteStatus | None = None,
        customer_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[SalesQuote, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100.")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer.")
        statement = select(SalesQuoteModel).where(
            SalesQuoteModel.company_id == self._company_id
        )
        if status is not None:
            statement = statement.where(SalesQuoteModel.status == status)
        if customer_id is not None:
            statement = statement.where(SalesQuoteModel.customer_id == customer_id)
        result = await self._session.scalars(
            statement.order_by(SalesQuoteModel.number, SalesQuoteModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_quote(model) for model in result)

    async def add_revision(
        self,
        quote: SalesQuote,
        revision: QuoteRevision,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> SalesQuote:
        self._validate_write(quote.company_id, actor_id)
        self._validate_revision(quote, revision, expected_version)
        result = await self._session.scalars(
            update(SalesQuoteModel)
            .where(
                SalesQuoteModel.company_id == self._company_id,
                SalesQuoteModel.id == quote.id,
                SalesQuoteModel.version == expected_version,
                SalesQuoteModel.status == SalesQuoteStatus.DRAFT,
            )
            .values(
                current_revision_number=quote.current_revision_number,
                version=quote.version,
                updated_by=actor_id,
                updated_at=datetime.now(UTC),
            )
            .returning(SalesQuoteModel)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        model = result.one_or_none()
        if model is None:
            raise OptimisticLockError(expected_version=expected_version)
        self._session.add(
            QuoteRevisionModel(
                id=revision.id,
                company_id=self._company_id,
                quote_id=quote.id,
                revision_number=revision.revision_number,
                gross_amount=revision.gross_amount,
                discount_amount=revision.discount_amount,
                net_amount=revision.net_amount,
                created_by=actor_id,
            )
        )
        # No ORM relationship is intentionally exposed between module-owned models;
        # establish the FK parent before flushing its immutable line records.
        await self._flush_conflict()
        snapshots = revision.pricing_snapshot_refs or (None,) * len(revision.items)
        for item, snapshot_id in zip(revision.items, snapshots, strict=True):
            self._session.add(
                QuoteRevisionItemModel(
                    id=item.id,
                    company_id=self._company_id,
                    revision_id=revision.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    discount_amount=item.discount_amount,
                    pricing_snapshot_id=snapshot_id,
                    created_by=actor_id,
                )
            )
        await self._flush_conflict()
        return _quote(model)

    async def get_revision(
        self, quote_id: UUID, revision_number: int
    ) -> QuoteRevision | None:
        revisions = await self._session.scalars(
            select(QuoteRevisionModel).where(
                QuoteRevisionModel.company_id == self._company_id,
                QuoteRevisionModel.quote_id == quote_id,
                QuoteRevisionModel.revision_number == revision_number,
            )
        )
        model = revisions.one_or_none()
        if model is None:
            return None
        items = await self._session.scalars(
            select(QuoteRevisionItemModel)
            .where(
                QuoteRevisionItemModel.company_id == self._company_id,
                QuoteRevisionItemModel.revision_id == model.id,
            )
            .order_by(QuoteRevisionItemModel.id)
        )
        return _revision(model, tuple(items))

    async def save(self, quote: SalesQuote, *, actor_id: UUID) -> SalesQuote:
        self._validate_write(quote.company_id, actor_id)
        expected_version = quote.version - 1
        if expected_version < 1:
            raise ValueError("save requires a changed aggregate version.")
        result = await self._session.scalars(
            update(SalesQuoteModel)
            .where(
                SalesQuoteModel.company_id == self._company_id,
                SalesQuoteModel.id == quote.id,
                SalesQuoteModel.version == expected_version,
            )
            .values(
                status=quote.status,
                workflow_instance_id=quote.workflow_instance_id,
                converted_order_id=quote.converted_order_id,
                version=quote.version,
                updated_by=actor_id,
                updated_at=datetime.now(UTC),
            )
            .returning(SalesQuoteModel)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        model = result.one_or_none()
        if model is None:
            raise OptimisticLockError(expected_version=expected_version)
        return _quote(model)

    def _validate_write(self, company_id: UUID, actor_id: UUID) -> None:
        if company_id != self._company_id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The sales quote is outside the selected company.",
                status_code=403,
            )
        if not isinstance(actor_id, UUID):
            raise ValueError("An explicit actor UUID is required.")

    def _validate_revision(
        self, quote: SalesQuote, revision: QuoteRevision, expected_version: int
    ) -> None:
        if revision.company_id != self._company_id or revision.quote_id != quote.id:
            raise ApplicationError(
                code="SCOPE_FORBIDDEN",
                message="The quote revision is outside the selected quote scope.",
                status_code=403,
            )
        if quote.version != expected_version + 1:
            raise ValueError("The revised aggregate must increment the expected version once.")
        if revision.revision_number != quote.current_revision_number:
            raise ValueError("Revision number must match the quote current revision.")

    async def _flush_conflict(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise ApplicationError(
                    code="SALES_QUOTE_CONFLICT",
                    message="This quote number or revision already exists.",
                    status_code=409,
                ) from error
            raise


__all__ = ["SalesQuoteRepository"]
