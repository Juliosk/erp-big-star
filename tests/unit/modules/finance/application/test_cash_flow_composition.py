"""Application-contract coverage for Cash Flow composition."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.application import (
    BankCashPosition,
    CashFlowCompositionService,
    ComposeCashFlowProjection,
    ReceivableCashFlowFeed,
)
from erp.modules.finance.domain import (
    BusinessCalendar,
    CashAmount,
    CashFlowCategory,
    CashFlowCertainty,
    CashFlowCurrencyMismatchError,
    CashFlowDateHorizon,
    CashFlowDirection,
    CashFlowEngine,
    CashFlowItem,
    CashFlowOrigin,
    CashFlowScenario,
    CashFlowScopeError,
    InvalidCashFlowError,
    ProjectionGranularity,
)


def _command(*, company_id: UUID | None = None) -> ComposeCashFlowProjection:
    tenant = company_id or uuid4()
    horizon = CashFlowDateHorizon(date(2026, 12, 1), date(2026, 12, 31))
    return ComposeCashFlowProjection(
        projection_id=uuid4(),
        company_id=tenant,
        as_of=horizon.start_on,
        calculated_at=datetime(2026, 12, 1, 8, tzinfo=UTC),
        horizon=horizon,
        granularity=ProjectionGranularity.DAILY,
        minimum_reserve=CashAmount(Decimal("100.00")),
        scenario=CashFlowScenario(uuid4(), "Base"),
    )


def _item(
    company_id: UUID,
    *,
    certainty: CashFlowCertainty = CashFlowCertainty.SCENARIO,
    origin: CashFlowOrigin = CashFlowOrigin.MANUAL_SCENARIO,
) -> CashFlowItem:
    return CashFlowItem(
        company_id=company_id,
        amount=CashAmount(Decimal("10.00")),
        occurs_on=date(2026, 12, 10),
        direction=CashFlowDirection.INFLOW,
        category=CashFlowCategory.OPERATING,
        certainty=certainty,
        origin=origin,
        reference_id=None if certainty is CashFlowCertainty.SCENARIO else uuid4(),
    )


@pytest.mark.parametrize("field_name", ["company_id", "bank_account_id", "statement_id"])
def test_bank_position_rejects_invalid_identity(field_name: str) -> None:
    values: dict[str, object] = {
        "company_id": uuid4(),
        "bank_account_id": uuid4(),
        "statement_id": uuid4(),
        "as_of": date(2026, 12, 1),
        "balance": CashAmount(Decimal("1.00")),
    }
    values[field_name] = UUID(int=0)
    with pytest.raises(InvalidCashFlowError, match=field_name):
        BankCashPosition(**values)  # type: ignore[arg-type]


def test_bank_position_rejects_invalid_date_and_balance() -> None:
    values = {
        "company_id": uuid4(),
        "bank_account_id": uuid4(),
        "statement_id": uuid4(),
        "as_of": date(2026, 12, 1),
        "balance": CashAmount(Decimal("1.00")),
    }
    with pytest.raises(InvalidCashFlowError, match="as_of"):
        BankCashPosition(**(values | {"as_of": datetime.now(UTC)}))  # type: ignore[arg-type]
    with pytest.raises(InvalidCashFlowError, match="balance"):
        BankCashPosition(**(values | {"balance": object()}))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("items", "available", "reason", "message"),
    [
        ([], True, None, "immutable tuple"),
        ((), 1, None, "boolean"),
        ((), True, "unexpected", "cannot contain"),
        ((object(),), True, None, "immutable tuple"),
        ((_item(uuid4()),), False, "missing", "cannot contain cash"),
        ((), False, None, "require a reason"),
    ],
)
def test_receivable_feed_contract_is_explicit(
    items: object,
    available: object,
    reason: object,
    message: str,
) -> None:
    with pytest.raises(InvalidCashFlowError, match=message):
        ReceivableCashFlowFeed(items=items, available=available, reason=reason)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"projection_id": UUID(int=0)}, "projection_id"),
        ({"company_id": UUID(int=0)}, "company_id"),
        ({"as_of": datetime.now(UTC)}, "as_of"),
        ({"calculated_at": datetime.now(UTC).replace(tzinfo=None)}, "timezone-aware"),
        (
            {"horizon": CashFlowDateHorizon(date(2026, 12, 2), date(2026, 12, 31))},
            "horizon",
        ),
        ({"granularity": "DAILY"}, "granularity"),
        ({"minimum_reserve": object()}, "minimum_reserve"),
        ({"scenario": object()}, "scenario"),
        ({"currency": "12"}, "currency"),
        ({"predicted_items": []}, "immutable tuple"),
        ({"predicted_items": (object(),)}, "CashFlowItem"),
    ],
)
def test_composition_command_rejects_invalid_contracts(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidCashFlowError, match=message):
        replace(_command(), **changes)  # type: ignore[arg-type]


def test_composition_command_rejects_authoritative_item_as_prediction() -> None:
    command = _command()
    authoritative = _item(
        command.company_id,
        certainty=CashFlowCertainty.COMMITTED,
        origin=CashFlowOrigin.RECEIVABLE_INSTALLMENT,
    )
    with pytest.raises(InvalidCashFlowError, match="manual-scenario"):
        replace(command, predicted_items=(authoritative,))


def test_composition_command_rejects_minimum_reserve_in_another_currency() -> None:
    with pytest.raises(CashFlowCurrencyMismatchError, match="another currency"):
        replace(_command(), minimum_reserve=CashAmount(Decimal("1.00"), "USD"))


class StaticBankPositions:
    def __init__(self, positions: tuple[BankCashPosition, ...]) -> None:
        self._positions = positions

    async def positions(
        self, *, company_id: UUID, as_of: date, currency: str
    ) -> tuple[BankCashPosition, ...]:
        del company_id, as_of, currency
        return self._positions


class EmptyPayables:
    async def commitments(
        self, *, company_id: UUID, horizon: CashFlowDateHorizon, currency: str
    ) -> tuple[CashFlowItem, ...]:
        del company_id, horizon, currency
        return ()


class AvailableReceivables:
    async def receivables(
        self, *, company_id: UUID, horizon: CashFlowDateHorizon, currency: str
    ) -> ReceivableCashFlowFeed:
        del company_id, horizon, currency
        return ReceivableCashFlowFeed((), True)


class UnusedProjectionStore:
    async def get(self, projection_id: UUID, *, version: int | None = None) -> None:
        del projection_id, version
        raise AssertionError("invalid positions must fail before persistence")

    async def add(self, projection: object, *, actor_id: UUID) -> None:
        del projection, actor_id
        raise AssertionError("unexpected add")

    async def save(
        self, projection: object, *, actor_id: UUID, expected_version: int
    ) -> None:
        del projection, actor_id, expected_version
        raise AssertionError("unexpected save")


def _service(position: BankCashPosition) -> CashFlowCompositionService:
    return CashFlowCompositionService(
        engine=CashFlowEngine(BusinessCalendar()),
        bank_positions=StaticBankPositions((position,)),
        payables=EmptyPayables(),
        receivables=AvailableReceivables(),
        projections=UnusedProjectionStore(),
    )


def test_service_rejects_invalid_command_and_actor() -> None:
    command = _command()
    position = BankCashPosition(
        command.company_id,
        uuid4(),
        uuid4(),
        command.as_of,
        CashAmount(Decimal("1.00")),
    )

    async def scenario() -> None:
        service = _service(position)
        with pytest.raises(InvalidCashFlowError, match="command"):
            await service.compose(object(), actor_id=uuid4())  # type: ignore[arg-type]
        with pytest.raises(InvalidCashFlowError, match="actor_id"):
            await service.compose(command, actor_id=UUID(int=0))

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["tenant", "future", "currency"])
def test_service_rejects_untrustworthy_bank_positions(failure: str) -> None:
    command = _command()
    position = BankCashPosition(
        uuid4() if failure == "tenant" else command.company_id,
        uuid4(),
        uuid4(),
        command.as_of + timedelta(days=1) if failure == "future" else command.as_of,
        CashAmount(Decimal("1.00"), "USD" if failure == "currency" else "BRL"),
    )

    async def scenario() -> None:
        expected: type[Exception] = (
            CashFlowScopeError if failure == "tenant" else InvalidCashFlowError
        )
        if failure == "currency":
            expected = CashFlowCurrencyMismatchError
        with pytest.raises(expected):
            await _service(position).compose(command, actor_id=uuid4())

    asyncio.run(scenario())
