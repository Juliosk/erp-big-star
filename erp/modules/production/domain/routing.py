"""Pure routing and work-center constraints."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from erp.modules.production.domain.exceptions import (
    InvalidProductionValueError,
    ProductionScopeError,
)
from erp.modules.production.domain.values import (
    EngineeringVersion,
    WorkCenterCode,
    normalized_decimal,
    require_uuid,
)


def _capability(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidProductionValueError("work center capability must be text.")
    normalized = value.strip().upper()
    if not normalized or len(normalized) > 64:
        raise InvalidProductionValueError(
            "work center capability must contain between 1 and 64 characters."
        )
    return normalized


@dataclass(frozen=True, slots=True)
class WorkCenter:
    company_id: UUID
    code: WorkCenterCode
    capabilities: frozenset[str]
    record_version: int = 1

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        if not isinstance(self.code, WorkCenterCode):
            raise InvalidProductionValueError("code must be a WorkCenterCode.")
        if not isinstance(self.capabilities, frozenset):
            raise InvalidProductionValueError("capabilities must be a frozenset.")
        object.__setattr__(
            self,
            "capabilities",
            frozenset(_capability(value) for value in self.capabilities),
        )
        if type(self.record_version) is not int or self.record_version < 1:
            raise InvalidProductionValueError("record_version must be a positive integer.")


@dataclass(frozen=True, slots=True)
class WorkCenterConstraint:
    company_id: UUID
    allowed_centers: tuple[WorkCenterCode, ...]
    required_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        if not isinstance(self.allowed_centers, tuple) or not self.allowed_centers:
            raise InvalidProductionValueError("allowed_centers must be a non-empty tuple.")
        if any(not isinstance(code, WorkCenterCode) for code in self.allowed_centers):
            raise InvalidProductionValueError("allowed_centers must contain WorkCenterCode values.")
        if len(self.allowed_centers) != len(set(self.allowed_centers)):
            raise InvalidProductionValueError("allowed work centers must be unique.")
        if not isinstance(self.required_capabilities, frozenset):
            raise InvalidProductionValueError("required_capabilities must be a frozenset.")
        object.__setattr__(
            self,
            "required_capabilities",
            frozenset(_capability(value) for value in self.required_capabilities),
        )

    def accepts(self, work_center: WorkCenter) -> bool:
        if not isinstance(work_center, WorkCenter):
            raise InvalidProductionValueError("work_center must be a WorkCenter.")
        if work_center.company_id != self.company_id:
            raise ProductionScopeError("work center belongs to another company.")
        return (
            work_center.code in self.allowed_centers
            and self.required_capabilities <= work_center.capabilities
        )


@dataclass(frozen=True, slots=True)
class RoutingOperation:
    sequence: int
    name: str
    work_center: WorkCenterConstraint
    setup_minutes: Decimal
    run_minutes_per_unit: Decimal

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise InvalidProductionValueError("operation sequence must be a positive integer.")
        if not isinstance(self.name, str):
            raise InvalidProductionValueError("operation name must be text.")
        name = " ".join(self.name.split())
        if not name or len(name) > 120:
            raise InvalidProductionValueError(
                "operation name must contain between 1 and 120 characters."
            )
        if not isinstance(self.work_center, WorkCenterConstraint):
            raise InvalidProductionValueError(
                "work_center must be a WorkCenterConstraint."
            )
        setup = normalized_decimal(self.setup_minutes, "setup_minutes")
        run = normalized_decimal(self.run_minutes_per_unit, "run_minutes_per_unit")
        if setup < 0 or run <= 0:
            raise InvalidProductionValueError(
                "setup_minutes cannot be negative and run_minutes_per_unit must be positive."
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "setup_minutes", setup)
        object.__setattr__(self, "run_minutes_per_unit", run)


@dataclass(frozen=True, slots=True)
class ProductionRouting:
    company_id: UUID
    product_id: UUID
    version: EngineeringVersion
    operations: tuple[RoutingOperation, ...]
    record_version: int = 1

    def __post_init__(self) -> None:
        require_uuid(self.company_id, "company_id")
        require_uuid(self.product_id, "product_id")
        if not isinstance(self.version, EngineeringVersion):
            raise InvalidProductionValueError("version must be an EngineeringVersion.")
        if not isinstance(self.operations, tuple) or not self.operations:
            raise InvalidProductionValueError("operations must be a non-empty tuple.")
        if any(not isinstance(operation, RoutingOperation) for operation in self.operations):
            raise InvalidProductionValueError(
                "operations must contain only RoutingOperation values."
            )
        if any(
            operation.work_center.company_id != self.company_id
            for operation in self.operations
        ):
            raise ProductionScopeError("routing operations must belong to the routing company.")
        sequences = tuple(operation.sequence for operation in self.operations)
        if len(sequences) != len(set(sequences)) or sequences != tuple(sorted(sequences)):
            raise InvalidProductionValueError(
                "operation sequences must be unique and ordered."
            )
        if type(self.record_version) is not int or self.record_version < 1:
            raise InvalidProductionValueError("record_version must be a positive integer.")


__all__ = [
    "ProductionRouting",
    "RoutingOperation",
    "WorkCenter",
    "WorkCenterConstraint",
]

