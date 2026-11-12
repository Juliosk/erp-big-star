"""M6 RFQ repository integration against real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from erp.modules.procurement.domain import (
    InvalidRequestForQuotationError,
    RequestForQuotation,
    RequestForQuotationConflictError,
    RequestForQuotationItem,
    RequestForQuotationScopeError,
    RequestForQuotationStatus,
    RequestForQuotationVersionConflictError,
    SupplierQuote,
    SupplierQuoteLine,
)
from erp.modules.procurement.infrastructure import (
    RequestForQuotationItemModel,
    RequestForQuotationModel,
    RequestForQuotationQuoteLineModel,
    RequestForQuotationRepository,
    RequestForQuotationSupplierModel,
    SupplierRepository,
)
from erp.modules.product.domain import Product
from tests.integration.test_procurement_purchasing_repository import purchasing_fixture
from tests.integration.test_procurement_supplier_repository import ProcurementFixture

pytestmark = pytest.mark.integration


def _rfq(
    data: ProcurementFixture,
    product: Product,
    supplier_id: UUID,
    **changes: object,
) -> RequestForQuotation:
    values: dict[str, object] = {
        "id": uuid4(),
        "company_id": data.company_id,
        "code": f"RFQ-{uuid4().hex[:10].upper()}",
        "created_by": data.actor_id,
        "response_deadline": date(2026, 12, 1),
        "items": (
            RequestForQuotationItem(
                id=uuid4(),
                product_id=product.id,
                quantity=Decimal("10"),
                uom="UN",
                required_on=date(2026, 12, 15),
                specification="Produto certificado",
            ),
        ),
        "invited_supplier_ids": (supplier_id,),
    }
    values.update(changes)
    return RequestForQuotation(**values)  # type: ignore[arg-type]


def _quote(rfq: RequestForQuotation, supplier_id: UUID) -> SupplierQuote:
    return SupplierQuote(
        id=uuid4(),
        supplier_id=supplier_id,
        currency="BRL",
        submitted_at=datetime(2026, 11, 12, tzinfo=UTC),
        valid_until=date(2026, 12, 31),
        lines=tuple(
            SupplierQuoteLine(
                rfq_item_id=item.id,
                offered_quantity=item.quantity,
                unit_price=Decimal("12.50"),
                lead_time_days=5,
            )
            for item in rfq.items
        ),
        freight_amount=Decimal("20.00"),
    )


@asynccontextmanager
async def rfq_fixture() -> AsyncIterator[tuple[ProcurementFixture, RequestForQuotation, UUID]]:
    async with purchasing_fixture() as (data, product, _):
        supplier = data.supplier()
        async with data.database.session() as session, session.begin():
            await SupplierRepository(session, company_id=data.company_id).add(
                supplier, actor_id=data.actor_id
            )
        rfq = _rfq(data, product, supplier.id)
        try:
            yield data, rfq, supplier.id
        finally:
            async with data.database.session() as session, session.begin():
                company_ids = (data.company_id, data.other_company_id)
                await session.execute(
                    delete(RequestForQuotationQuoteLineModel).where(
                        RequestForQuotationQuoteLineModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(RequestForQuotationSupplierModel).where(
                        RequestForQuotationSupplierModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(RequestForQuotationItemModel).where(
                        RequestForQuotationItemModel.company_id.in_(company_ids)
                    )
                )
                await session.execute(
                    delete(RequestForQuotationModel).where(
                        RequestForQuotationModel.company_id.in_(company_ids)
                    )
                )


def test_rfq_round_trip_quotes_award_filters_and_row_lock() -> None:
    async def scenario() -> None:
        async with (
            rfq_fixture() as (data, rfq, supplier_id),
            data.database.session() as session,
            session.begin(),
        ):
            repository = RequestForQuotationRepository(session, company_id=data.company_id)
            await repository.add(rfq, actor_id=data.actor_id)
            assert await repository.get(rfq.id) == rfq
            assert await repository.get_for_update(rfq.id) == rfq
            assert await repository.list(status=RequestForQuotationStatus.DRAFT) == (rfq,)

            opened = rfq.open(occurred_at=datetime(2026, 11, 11, tzinfo=UTC))
            await repository.save(opened, actor_id=data.actor_id)
            quoted = opened.record_quote(_quote(rfq, supplier_id))
            await repository.save(quoted, actor_id=data.actor_id)
            closed = quoted.close(occurred_at=datetime(2026, 11, 13, tzinfo=UTC))
            await repository.save(closed, actor_id=data.actor_id)
            awarded = closed.award_quote(
                quote_id=quoted.supplier_quotes[0].id,
                actor_id=uuid4(),
                occurred_at=datetime(2026, 11, 14, tzinfo=UTC),
            )
            await repository.save(awarded, actor_id=data.actor_id)
            assert await repository.get(rfq.id) == awarded

    asyncio.run(scenario())


def test_rfq_repository_is_tenant_bound_and_translates_conflicts() -> None:
    async def scenario() -> None:
        async with (
            rfq_fixture() as (data, rfq, _),
            data.database.session() as session,
            session.begin(),
        ):
            repository = RequestForQuotationRepository(session, company_id=data.company_id)
            await repository.add(rfq, actor_id=data.actor_id)
            foreign = RequestForQuotationRepository(session, company_id=data.other_company_id)
            assert await foreign.get(rfq.id) is None
            with pytest.raises(RequestForQuotationScopeError):
                await foreign.add(rfq, actor_id=data.actor_id)

            duplicate = replace(
                rfq,
                id=uuid4(),
                items=tuple(replace(item, id=uuid4()) for item in rfq.items),
            )
            savepoint = await session.begin_nested()
            with pytest.raises(RequestForQuotationConflictError):
                await repository.add(duplicate, actor_id=data.actor_id)
            await savepoint.rollback()

            opened = rfq.open(occurred_at=datetime.now(UTC))
            await repository.save(opened, actor_id=data.actor_id)
            with pytest.raises(RequestForQuotationVersionConflictError):
                await repository.save(opened, actor_id=data.actor_id, expected_version=1)

    asyncio.run(scenario())


def test_rfq_repository_rejects_invalid_contract_and_snapshot_drift() -> None:
    async def scenario() -> None:
        async with (
            rfq_fixture() as (data, rfq, _),
            data.database.session() as session,
            session.begin(),
        ):
            with pytest.raises(ValueError, match="company UUID"):
                RequestForQuotationRepository(session, company_id=UUID(int=0))
            repository = RequestForQuotationRepository(session, company_id=data.company_id)
            with pytest.raises(TypeError, match="RequestForQuotation"):
                await repository.add(object(), actor_id=data.actor_id)  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="actor UUID"):
                await repository.add(rfq, actor_id=UUID(int=0))
            with pytest.raises(ValueError, match="start draft"):
                await repository.add(
                    rfq.open(occurred_at=datetime.now(UTC)),
                    actor_id=data.actor_id,
                )
            await repository.add(rfq, actor_id=data.actor_id)
            opened = rfq.open(occurred_at=datetime.now(UTC))
            with pytest.raises(InvalidRequestForQuotationError, match="immutable"):
                await repository.save(
                    replace(opened, code="CHANGED"),
                    actor_id=data.actor_id,
                )
            with pytest.raises(ValueError, match="version increment"):
                await repository.save(rfq, actor_id=data.actor_id)
            with pytest.raises(ValueError, match="limit"):
                await repository.list(limit=0)
            with pytest.raises(ValueError, match="offset"):
                await repository.list(offset=-1)
            with pytest.raises(ValueError, match="official"):
                await repository.list(status="DRAFT")  # type: ignore[arg-type]

    asyncio.run(scenario())
