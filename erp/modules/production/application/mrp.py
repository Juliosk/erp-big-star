"""Application orchestration for deterministic, tenant-bound MRP runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID

from erp.modules.production.domain import (
    BillOfMaterials,
    InvalidProductionValueError,
    MRPDemand,
    MRPEngine,
    MRPInventoryPosition,
    MRPPlan,
    MRPPlanningPolicy,
    MRPScheduledReceipt,
    ProductionScopeError,
)


def _nonzero_uuid(value: object, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidProductionValueError(f"{field} must be a non-zero UUID.")
    return value


def _aware_datetime(value: object, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise InvalidProductionValueError(f"{field} must be timezone-aware.")
    return value


@dataclass(frozen=True, slots=True)
class MRPSupplySnapshot:
    """Authoritative stock and already-scheduled supply at planning time."""

    inventory: tuple[MRPInventoryPosition, ...] = ()
    scheduled_receipts: tuple[MRPScheduledReceipt, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.inventory, tuple) or any(
            not isinstance(value, MRPInventoryPosition) for value in self.inventory
        ):
            raise InvalidProductionValueError(
                "inventory must be a tuple of MRPInventoryPosition values."
            )
        if not isinstance(self.scheduled_receipts, tuple) or any(
            not isinstance(value, MRPScheduledReceipt)
            for value in self.scheduled_receipts
        ):
            raise InvalidProductionValueError(
                "scheduled_receipts must be a tuple of MRPScheduledReceipt values."
            )


@dataclass(frozen=True, slots=True)
class MRPEngineeringSnapshot:
    """Effective engineering structures and planning policies for one run."""

    boms: tuple[BillOfMaterials, ...]
    policies: tuple[MRPPlanningPolicy, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.boms, tuple) or any(
            not isinstance(value, BillOfMaterials) for value in self.boms
        ):
            raise InvalidProductionValueError(
                "boms must be a tuple of BillOfMaterials values."
            )
        if not isinstance(self.policies, tuple) or any(
            not isinstance(value, MRPPlanningPolicy) for value in self.policies
        ):
            raise InvalidProductionValueError(
                "policies must be a tuple of MRPPlanningPolicy values."
            )


class MRPDemandProvider(Protocol):
    async def demands(
        self,
        *,
        company_id: UUID,
        as_of: date,
        horizon_end: date,
    ) -> tuple[MRPDemand, ...]: ...


class MRPSupplyProvider(Protocol):
    async def supply(
        self,
        *,
        company_id: UUID,
        as_of: date,
        horizon_end: date,
    ) -> MRPSupplySnapshot: ...


class MRPEngineeringProvider(Protocol):
    async def engineering(
        self,
        *,
        company_id: UUID,
        as_of: date,
        horizon_end: date,
    ) -> MRPEngineeringSnapshot: ...


class MRPRunStore(Protocol):
    async def add(self, run: MRPRun, *, actor_id: UUID) -> None: ...

    async def get(self, run_id: UUID) -> MRPRun | None: ...


@dataclass(frozen=True, slots=True)
class ExecuteMRP:
    run_id: UUID
    company_id: UUID
    as_of: date
    horizon_end: date
    requested_at: datetime

    def __post_init__(self) -> None:
        _nonzero_uuid(self.run_id, "run_id")
        _nonzero_uuid(self.company_id, "company_id")
        if type(self.as_of) is not date or type(self.horizon_end) is not date:
            raise InvalidProductionValueError(
                "as_of and horizon_end must be dates."
            )
        if self.horizon_end < self.as_of:
            raise InvalidProductionValueError(
                "horizon_end cannot precede as_of."
            )
        _aware_datetime(self.requested_at, "requested_at")


@dataclass(frozen=True, slots=True)
class MRPRun:
    """Immutable, reproducible execution snapshot persisted with its plan."""

    id: UUID
    company_id: UUID
    as_of: date
    horizon_end: date
    started_at: datetime
    completed_at: datetime
    plan: MRPPlan
    inventory: tuple[MRPInventoryPosition, ...]
    scheduled_receipts: tuple[MRPScheduledReceipt, ...]
    boms: tuple[BillOfMaterials, ...]
    policies: tuple[MRPPlanningPolicy, ...]
    engine_version: str = "MRP_V1"
    record_version: int = 1

    def __post_init__(self) -> None:
        _nonzero_uuid(self.id, "id")
        _nonzero_uuid(self.company_id, "company_id")
        if type(self.as_of) is not date or type(self.horizon_end) is not date:
            raise InvalidProductionValueError(
                "as_of and horizon_end must be dates."
            )
        if self.horizon_end < self.as_of:
            raise InvalidProductionValueError(
                "horizon_end cannot precede as_of."
            )
        _aware_datetime(self.started_at, "started_at")
        _aware_datetime(self.completed_at, "completed_at")
        if self.completed_at < self.started_at:
            raise InvalidProductionValueError(
                "completed_at cannot precede started_at."
            )
        if not isinstance(self.plan, MRPPlan):
            raise InvalidProductionValueError("plan must be an MRPPlan.")
        MRPSupplySnapshot(self.inventory, self.scheduled_receipts)
        MRPEngineeringSnapshot(self.boms, self.policies)
        if self.plan.company_id != self.company_id or self.plan.as_of != self.as_of:
            raise ProductionScopeError(
                "MRP run and calculated plan must share company and reference date."
            )
        if (
            any(value.company_id != self.company_id for value in self.inventory)
            or any(
                value.company_id != self.company_id
                for value in self.scheduled_receipts
            )
            or any(value.company_id != self.company_id for value in self.boms)
            or any(value.company_id != self.company_id for value in self.policies)
        ):
            raise ProductionScopeError("MRP run inputs must belong to one company.")
        engine_version = self.engine_version.strip().upper()
        if not engine_version or len(engine_version) > 32:
            raise InvalidProductionValueError(
                "engine_version must contain up to 32 characters."
            )
        if type(self.record_version) is not int or self.record_version < 1:
            raise InvalidProductionValueError(
                "record_version must be a positive integer."
            )
        object.__setattr__(self, "engine_version", engine_version)


class MRPApplicationService:
    """Load authoritative inputs, run the pure engine and persist atomically."""

    def __init__(
        self,
        *,
        demands: MRPDemandProvider,
        supply: MRPSupplyProvider,
        engineering: MRPEngineeringProvider,
        runs: MRPRunStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._demands = demands
        self._supply = supply
        self._engineering = engineering
        self._runs = runs
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, command: ExecuteMRP, *, actor_id: UUID) -> MRPRun:
        if not isinstance(command, ExecuteMRP):
            raise InvalidProductionValueError("command must be an ExecuteMRP.")
        _nonzero_uuid(actor_id, "actor_id")
        demands = await self._demands.demands(
            company_id=command.company_id,
            as_of=command.as_of,
            horizon_end=command.horizon_end,
        )
        supply = await self._supply.supply(
            company_id=command.company_id,
            as_of=command.as_of,
            horizon_end=command.horizon_end,
        )
        engineering = await self._engineering.engineering(
            company_id=command.company_id,
            as_of=command.as_of,
            horizon_end=command.horizon_end,
        )
        self._validate_horizon(command, demands, supply)
        engine = MRPEngine(
            company_id=command.company_id,
            boms=engineering.boms,
            policies=engineering.policies,
        )
        plan = engine.plan(
            as_of=command.as_of,
            demands=demands,
            inventory=supply.inventory,
            scheduled_receipts=supply.scheduled_receipts,
        )
        run = MRPRun(
            id=command.run_id,
            company_id=command.company_id,
            as_of=command.as_of,
            horizon_end=command.horizon_end,
            started_at=command.requested_at,
            completed_at=_aware_datetime(self._clock(), "completed_at"),
            plan=plan,
            inventory=supply.inventory,
            scheduled_receipts=supply.scheduled_receipts,
            boms=engineering.boms,
            policies=engineering.policies,
        )
        await self._runs.add(run, actor_id=actor_id)
        return run

    @staticmethod
    def _validate_horizon(
        command: ExecuteMRP,
        demands: tuple[MRPDemand, ...],
        supply: MRPSupplySnapshot,
    ) -> None:
        if not isinstance(demands, tuple) or not demands or any(
            not isinstance(value, MRPDemand) for value in demands
        ):
            raise InvalidProductionValueError(
                "demand provider must return a non-empty tuple of MRPDemand values."
            )
        if not isinstance(supply, MRPSupplySnapshot):
            raise InvalidProductionValueError(
                "supply provider must return an MRPSupplySnapshot."
            )
        if any(
            value.required_on < command.as_of
            or value.required_on > command.horizon_end
            for value in demands
        ):
            raise InvalidProductionValueError(
                "demand provider returned values outside the requested horizon."
            )
        if any(
            value.available_on > command.horizon_end
            for value in supply.scheduled_receipts
        ):
            raise InvalidProductionValueError(
                "supply provider returned receipts after the requested horizon."
            )


__all__ = [
    "ExecuteMRP",
    "MRPApplicationService",
    "MRPDemandProvider",
    "MRPEngineeringProvider",
    "MRPEngineeringSnapshot",
    "MRPRun",
    "MRPRunStore",
    "MRPSupplyProvider",
    "MRPSupplySnapshot",
]
