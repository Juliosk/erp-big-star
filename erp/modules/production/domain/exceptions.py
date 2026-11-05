"""Pure production-domain errors with stable business codes."""


class ProductionDomainError(ValueError):
    """Base error for invalid production-domain decisions."""

    code = "PRODUCTION_DOMAIN_ERROR"


class InvalidProductionValueError(ProductionDomainError):
    code = "INVALID_PRODUCTION_VALUE"


class BomCycleError(ProductionDomainError):
    code = "BOM_CYCLE_DETECTED"


class BomNotFoundError(ProductionDomainError):
    code = "BOM_NOT_FOUND"


class ProductionScopeError(ProductionDomainError):
    code = "PRODUCTION_SCOPE_VIOLATION"


class UnitOfMeasureMismatchError(ProductionDomainError):
    code = "UOM_MISMATCH"


class ProductionConflictError(ProductionDomainError):
    code = "PRODUCTION_CONFLICT"


class ProductionVersionConflictError(ProductionDomainError):
    code = "VERSION_CONFLICT"

    def __init__(self, expected_version: int) -> None:
        self.expected_version = expected_version
        super().__init__(f"The production resource changed after version {expected_version}.")


class InvalidProductionOrderStateError(ProductionDomainError):
    code = "INVALID_PRODUCTION_ORDER_STATE"


class EngineeringUnavailableError(ProductionDomainError):
    code = "ENGINEERING_UNAVAILABLE"


class ProductionQuantityExceededError(ProductionDomainError):
    code = "PRODUCTION_QUANTITY_EXCEEDED"


class RoutingConsistencyError(ProductionDomainError):
    code = "ROUTING_INCONSISTENT"


class LotTraceabilityError(ProductionDomainError):
    code = "LOT_TRACEABILITY_ERROR"


__all__ = [
    "BomCycleError",
    "BomNotFoundError",
    "EngineeringUnavailableError",
    "InvalidProductionOrderStateError",
    "InvalidProductionValueError",
    "LotTraceabilityError",
    "ProductionConflictError",
    "ProductionDomainError",
    "ProductionQuantityExceededError",
    "ProductionScopeError",
    "ProductionVersionConflictError",
    "RoutingConsistencyError",
    "UnitOfMeasureMismatchError",
]

