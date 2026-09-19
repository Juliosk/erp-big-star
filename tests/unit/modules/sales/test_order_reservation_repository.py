"""Tenant boundary for the M4 order reservation projection."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.sales.domain import SalesOrder, SalesOrderReservation
from erp.modules.sales.infrastructure import SalesOrderReservationRepository
from erp.platform.errors import ApplicationError


def _approved_order(company_id: UUID) -> SalesOrder:
    return SalesOrder.create_from_quote(
        company_id=company_id,
        number="SO-SCOPE-1",
        source_quote_id=uuid4(),
        source_quote_revision_number=1,
        customer_id=uuid4(),
        seller_id=uuid4(),
        currency="BRL",
        lines=((uuid4(), uuid4(), "1", "10", "0", None),),
    ).approve()


def test_repository_rejects_cross_company_projection_before_touching_session() -> None:
    async def scenario() -> None:
        selected_company = uuid4()
        reservation = SalesOrderReservation.request(_approved_order(uuid4()))
        repository = SalesOrderReservationRepository(
            cast(AsyncSession, object()), company_id=selected_company
        )
        with pytest.raises(ApplicationError) as captured:
            await repository.add(reservation, actor_id=uuid4())
        assert captured.value.code == "SCOPE_FORBIDDEN"

    asyncio.run(scenario())
