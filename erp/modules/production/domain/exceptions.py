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


__all__ = [
    "BomCycleError",
    "BomNotFoundError",
    "InvalidProductionValueError",
    "ProductionDomainError",
    "ProductionScopeError",
    "UnitOfMeasureMismatchError",
]

