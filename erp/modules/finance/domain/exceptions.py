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


class InvalidPayableStateError(FinanceDomainError):
    """A payable or installment lifecycle transition is not allowed."""

    code = "INVALID_PAYABLE_STATE"


class InvalidPayableError(FinanceDomainError):
    """A payable aggregate invariant is invalid."""

    code = "INVALID_PAYABLE"


class InstallmentMismatchError(FinanceDomainError):
    """Installments do not reconcile with the title total or identity."""

    code = "INSTALLMENT_MISMATCH"


class InvalidProvisionalEntryError(FinanceDomainError):
    """A provisional financial entry invariant is invalid."""

    code = "INVALID_PROVISIONAL_ENTRY"


class SodViolationError(FinanceDomainError):
    """The same actor attempted a forbidden high-value self-approval."""

    code = "SOD_VIOLATION"


class SegregationOfDutiesViolation(SodViolationError):
    """Backward-compatible explicit name for the M12 SoD violation."""


class PayableConflictError(FinanceDomainError):
    """A payable or provisional entry conflicts with an existing identity."""

    code = "PAYABLE_CONFLICT"


class PayableDivergenceBlockedError(FinanceDomainError):
    """An unresolved fiscal or purchasing divergence blocks the title."""

    code = "PAYABLE_DIVERGENCE_BLOCKED"


class PayableApprovalRequiredError(FinanceDomainError):
    """The title still requires a valid M22 approval decision."""

    code = "PAYABLE_APPROVAL_REQUIRED"


class FinanceVersionConflictError(FinanceDomainError):
    """A persisted M12 aggregate was changed by another transaction."""

    code = "VERSION_CONFLICT"


class FinanceScopeError(FinanceDomainError):
    """An aggregate does not belong to the repository company boundary."""

    code = "FINANCE_SCOPE_ERROR"


__all__ = [
    "FinanceDomainError",
    "FinanceScopeError",
    "FinanceVersionConflictError",
    "InstallmentMismatchError",
    "InvalidFinanceContractError",
    "InvalidPayableError",
    "InvalidPayableStateError",
    "InvalidProvisionalEntryError",
    "InvalidSegregationPolicyError",
    "PayableApprovalRequiredError",
    "PayableConflictError",
    "PayableDivergenceBlockedError",
    "SegregationOfDutiesViolation",
    "SodViolationError",
]
