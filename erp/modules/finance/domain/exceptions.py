"""Framework-free M12 domain failures."""


class FinanceDomainError(ValueError):
    """Base error for violated Finance invariants."""

    code = "FINANCE_DOMAIN_ERROR"


class InvalidFinanceContractError(FinanceDomainError):
    """A public M12 integration contract is structurally inconsistent."""

    code = "INVALID_FINANCE_CONTRACT"


class InvalidSegregationPolicyError(FinanceDomainError):
    """A segregation policy or approval input is invalid."""

    code = "INVALID_SEGREGATION_POLICY"


class SegregationOfDutiesViolation(FinanceDomainError):
    """The same actor attempted a forbidden high-value self-approval."""

    code = "SOD_VIOLATION"


__all__ = [
    "FinanceDomainError",
    "InvalidFinanceContractError",
    "InvalidSegregationPolicyError",
    "SegregationOfDutiesViolation",
]
