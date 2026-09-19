"""M4 reservation application boundary and authorization."""

import asyncio
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.admin.contracts import SecurityContext
from erp.modules.sales.application import (
    SALES_ORDER_RESERVE,
    CommandMetadata,
    ReserveSalesOrder,
    SalesAuthorization,
    SalesOrderReservationResult,
    SalesOrderReservationService,
)


class AuthorizationStub:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, object, bool]] = []

    async def require(
        self,
        context: SecurityContext,
        company_id: UUID,
        permission: object,
        *,
        write: bool = False,
    ) -> None:
        self.calls.append((company_id, permission, write))


class StoreStub:
    def __init__(self) -> None:
        self.actor_id: UUID | None = None

    async def reserve(
        self, command: ReserveSalesOrder, actor_id: UUID
    ) -> SalesOrderReservationResult:
        self.actor_id = actor_id
        raise RuntimeError("transaction adapter reached")


def test_reservation_service_authorizes_critical_write_before_transaction() -> None:
    async def scenario() -> None:
        company_id, actor_id = uuid4(), uuid4()
        authorization = AuthorizationStub()
        store = StoreStub()
        service = SalesOrderReservationService(
            store, cast(SalesAuthorization, authorization)
        )
        command = ReserveSalesOrder(
            company_id=company_id,
            order_id=uuid4(),
            warehouse_id=uuid4(),
            idempotency_key="order-reserve-1",
            metadata=CommandMetadata(
                request_id=uuid4(), correlation_id=uuid4(), source_ip=None
            ),
        )
        context = cast(SecurityContext, type("Context", (), {
            "principal": type("Principal", (), {"user_id": actor_id})()
        })())

        with pytest.raises(RuntimeError, match="adapter reached"):
            await service.reserve(context, command)
        assert authorization.calls == [(company_id, SALES_ORDER_RESERVE, True)]
        assert store.actor_id == actor_id
        assert command.payload()["reservation_kind"] == "HARD"

    asyncio.run(scenario())
