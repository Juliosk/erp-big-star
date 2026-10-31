"""Application orchestration for authoritative Cash Flow composition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from erp.modules.finance.domain import (
    CashAmount,
    CashFlowCertainty,
    CashFlowCurrencyMismatchError,
    CashFlowDateHorizon,
    CashFlowEngine,
    CashFlowItem,
    CashFlowMissingSource,
    CashFlowOrigin,
    CashFlowProjection,
    CashFlowProjectionInput,
    CashFlowScenario,
    CashFlowScopeError,
    CashFlowSourceGap,
    InvalidCashFlowError,
    ProjectionGranularity,
)


@dataclass(frozen=True, slots=True)
class BankCashPosition:
    """Latest authoritative closing balance for one tenant bank account."""

    company_id: UUID
    bank_account_id: UUID
    statement_id: UUID
    as_of: date
    balance: CashAmount

    def __post_init__(self) -> None:
        for field_name in ("company_id", "bank_account_id", "statement_id"):
            value = getattr(self, field_name)
            if not isinstance(value, UUID) or value.int == 0:
                raise InvalidCashFlowError(f"{field_name} must be a non-zero UUID.")
        if type(self.as_of) is not date:
            raise InvalidCashFlowError("bank position as_of must be a date.")
        if not isinstance(self.balance, CashAmount):
            raise InvalidCashFlowError("bank position balance must be a CashAmount.")


@dataclass(frozen=True, slots=True)
class ReceivableCashFlowFeed:
    """Explicit M13 availability result; unavailable never means zero receivables."""

    items: tuple[CashFlowItem, ...]
    available: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple) or any(
            not isinstance(item, CashFlowItem) for item in self.items
        ):
            raise InvalidCashFlowError("receivable feed items must be an immutable tuple.")
        if type(self.available) is not bool:
            raise InvalidCashFlowError("receivable feed availability must be boolean.")
        normalized_reason = " ".join(self.reason.split()) if isinstance(self.reason, str) else None
        if self.available and normalized_reason is not None:
            raise InvalidCashFlowError("available receivable feeds cannot contain a gap reason.")
        if not self.available:
            if self.items:
                raise InvalidCashFlowError("unavailable receivable feeds cannot contain cash items.")
            if not normalized_reason or len(normalized_reason) > 500:
                raise InvalidCashFlowError(
                    "unavailable receivable feeds require a reason with up to 500 characters."
                )
        object.__setattr__(self, "reason", normalized_reason)


class BankPositionProvider(Protocol):
    async def positions(
        self,
        *,
        company_id: UUID,
        as_of: date,
        currency: str,
    ) -> tuple[BankCashPosition, ...]: ...


class PayableCommitmentProvider(Protocol):
    async def commitments(
        self,
        *,
        company_id: UUID,
        horizon: CashFlowDateHorizon,
        currency: str,
    ) -> tuple[CashFlowItem, ...]: ...


class ReceivableCashFlowProvider(Protocol):
    async def receivables(
        self,
        *,
        company_id: UUID,
        horizon: CashFlowDateHorizon,
        currency: str,
    ) -> ReceivableCashFlowFeed: ...


class CashFlowProjectionStore(Protocol):
    async def get(
        self,
        projection_id: UUID,
        *,
        version: int | None = None,
    ) -> CashFlowProjection | None: ...

    async def add(self, projection: CashFlowProjection, *, actor_id: UUID) -> None: ...

    async def save(
        self,
        projection: CashFlowProjection,
        *,
        actor_id: UUID,
        expected_version: int,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ComposeCashFlowProjection:
    projection_id: UUID
    company_id: UUID
    as_of: date
    calculated_at: datetime
    horizon: CashFlowDateHorizon
    granularity: ProjectionGranularity
    minimum_reserve: CashAmount
    scenario: CashFlowScenario
    predicted_items: tuple[CashFlowItem, ...] = ()
    currency: str = "BRL"

    def __post_init__(self) -> None:
        for field_name in ("projection_id", "company_id"):
            value = getattr(self, field_name)
            if not isinstance(value, UUID) or value.int == 0:
                raise InvalidCashFlowError(f"{field_name} must be a non-zero UUID.")
        if type(self.as_of) is not date:
            raise InvalidCashFlowError("as_of must be a date.")
        if (
            not isinstance(self.calculated_at, datetime)
            or self.calculated_at.tzinfo is None
            or self.calculated_at.utcoffset() is None
        ):
            raise InvalidCashFlowError("calculated_at must be timezone-aware.")
        if not isinstance(self.horizon, CashFlowDateHorizon) or self.horizon.start_on != self.as_of:
            raise InvalidCashFlowError("horizon must be a Cash Flow horizon starting on as_of.")
        if not isinstance(self.granularity, ProjectionGranularity):
            raise InvalidCashFlowError("granularity must be a ProjectionGranularity.")
        if not isinstance(self.minimum_reserve, CashAmount):
            raise InvalidCashFlowError("minimum_reserve must be a CashAmount.")
        if not isinstance(self.scenario, CashFlowScenario):
            raise InvalidCashFlowError("scenario must be a CashFlowScenario.")
        currency = self.currency.strip().upper() if isinstance(self.currency, str) else ""
        if len(currency) != 3 or not currency.isalpha() or not currency.isascii():
            raise InvalidCashFlowError("currency must use an ISO 4217 alpha-3 code.")
        if self.minimum_reserve.currency != currency:
            raise CashFlowCurrencyMismatchError("minimum reserve uses another currency.")
        if not isinstance(self.predicted_items, tuple):
            raise InvalidCashFlowError("predicted_items must be an immutable tuple.")
        for item in self.predicted_items:
            if not isinstance(item, CashFlowItem):
                raise InvalidCashFlowError("predicted_items must contain CashFlowItem values.")
            if (
                item.certainty is not CashFlowCertainty.SCENARIO
                or item.origin is not CashFlowOrigin.MANUAL_SCENARIO
            ):
                raise InvalidCashFlowError(
                    "predicted items must remain explicit manual-scenario assumptions."
                )
        object.__setattr__(self, "currency", currency)


@dataclass(frozen=True, slots=True)
class CashFlowCompositionResult:
    projection: CashFlowProjection
    bank_positions: tuple[BankCashPosition, ...]
    committed_items: tuple[CashFlowItem, ...]
    receivable_items: tuple[CashFlowItem, ...]
    predicted_items: tuple[CashFlowItem, ...]
    source_gaps: tuple[CashFlowSourceGap, ...]


@dataclass(frozen=True, slots=True)
class UnavailableReceivableProvider:
    """Official pre-M13 adapter: absence is reported, never estimated."""

    reason: str = "M13 receivables source is not available for this projection horizon."

    async def receivables(
        self,
        *,
        company_id: UUID,
        horizon: CashFlowDateHorizon,
        currency: str,
    ) -> ReceivableCashFlowFeed:
        del company_id, horizon, currency
        return ReceivableCashFlowFeed(items=(), available=False, reason=self.reason)


class CashFlowCompositionService:
    """Collect authoritative sources, calculate one snapshot and persist atomically."""

    def __init__(
        self,
        *,
        engine: CashFlowEngine,
        bank_positions: BankPositionProvider,
        payables: PayableCommitmentProvider,
        receivables: ReceivableCashFlowProvider,
        projections: CashFlowProjectionStore,
    ) -> None:
        self._engine = engine
        self._bank_positions = bank_positions
        self._payables = payables
        self._receivables = receivables
        self._projections = projections

    async def compose(
        self,
        command: ComposeCashFlowProjection,
        *,
        actor_id: UUID,
    ) -> CashFlowCompositionResult:
        if not isinstance(command, ComposeCashFlowProjection):
            raise InvalidCashFlowError("command must be a ComposeCashFlowProjection.")
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise InvalidCashFlowError("actor_id must be a non-zero UUID.")

        positions = await self._bank_positions.positions(
            company_id=command.company_id,
            as_of=command.as_of,
            currency=command.currency,
        )
        gaps: list[CashFlowSourceGap] = []
        opening_amount = Decimal("0.00")
        for position in positions:
            if position.company_id != command.company_id:
                raise CashFlowScopeError("bank position belongs to another company.")
            if position.as_of > command.as_of:
                raise InvalidCashFlowError("bank position is newer than the projection reference date.")
            if position.balance.currency != command.currency:
                raise CashFlowCurrencyMismatchError("bank position uses another currency.")
            opening_amount += position.balance.amount
        if not positions:
            gaps.append(
                CashFlowSourceGap(
                    company_id=command.company_id,
                    source=CashFlowMissingSource.BANK_POSITION,
                    horizon=command.horizon,
                    reason="No authoritative reconciled bank closing balance exists at the reference date.",
                )
            )

        committed = await self._payables.commitments(
            company_id=command.company_id,
            horizon=command.horizon,
            currency=command.currency,
        )
        receivable_feed = await self._receivables.receivables(
            company_id=command.company_id,
            horizon=command.horizon,
            currency=command.currency,
        )
        if not receivable_feed.available:
            gaps.append(
                CashFlowSourceGap(
                    company_id=command.company_id,
                    source=CashFlowMissingSource.RECEIVABLES,
                    horizon=command.horizon,
                    reason=receivable_feed.reason or "M13 receivables source is unavailable.",
                )
            )

        current = await self._projections.get(command.projection_id)
        version = 1 if current is None else current.version + 1
        request = CashFlowProjectionInput(
            projection_id=command.projection_id,
            company_id=command.company_id,
            as_of=command.as_of,
            calculated_at=command.calculated_at,
            horizon=command.horizon,
            granularity=command.granularity,
            opening_balance=CashAmount(opening_amount, command.currency),
            minimum_reserve=command.minimum_reserve,
            scenario=command.scenario,
            items=(*committed, *receivable_feed.items, *command.predicted_items),
            source_gaps=tuple(gaps),
            version=version,
        )
        projection = self._engine.project(request)
        if current is None:
            await self._projections.add(projection, actor_id=actor_id)
        else:
            await self._projections.save(
                projection,
                actor_id=actor_id,
                expected_version=current.version,
            )
        return CashFlowCompositionResult(
            projection=projection,
            bank_positions=positions,
            committed_items=committed,
            receivable_items=receivable_feed.items,
            predicted_items=command.predicted_items,
            source_gaps=tuple(gaps),
        )


__all__ = [
    "BankCashPosition",
    "BankPositionProvider",
    "CashFlowCompositionResult",
    "CashFlowCompositionService",
    "CashFlowProjectionStore",
    "ComposeCashFlowProjection",
    "PayableCommitmentProvider",
    "ReceivableCashFlowFeed",
    "ReceivableCashFlowProvider",
    "UnavailableReceivableProvider",
]
