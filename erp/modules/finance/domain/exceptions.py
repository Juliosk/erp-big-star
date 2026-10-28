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


class InvalidTreasuryRuleError(FinanceDomainError):
    """A treasury value object or payment-batch invariant is invalid."""

    code = "INVALID_TREASURY_RULE"


class PaymentInstallmentIneligibleError(FinanceDomainError):
    """A payable installment cannot participate in payment execution."""

    code = "PAYMENT_INSTALLMENT_INELIGIBLE"


class TreasurySodViolationError(SodViolationError):
    """A treasury actor conflicts with the payable or batch maker-checker rules."""


class TreasuryConflictError(FinanceDomainError):
    """A payment batch conflicts with an existing company-scoped identity."""

    code = "TREASURY_CONFLICT"


class TreasuryVersionConflictError(FinanceDomainError):
    """A payment batch was changed by another transaction."""

    code = "VERSION_CONFLICT"


class TreasuryScopeError(FinanceDomainError):
    """A payment batch does not belong to the selected company."""

    code = "TREASURY_SCOPE_ERROR"


class InvalidBankStatementError(FinanceDomainError):
    """A bank statement, movement or reconciliation rule is inconsistent."""

    code = "INVALID_BANK_STATEMENT"


class BankMovementAlreadyReconciledError(FinanceDomainError):
    """A reconciled bank movement cannot be reconciled a second time."""

    code = "BANK_MOVEMENT_ALREADY_RECONCILED"


class BankStatementConflictError(FinanceDomainError):
    """A bank-statement import conflicts with an existing tenant identity."""

    code = "BANK_STATEMENT_CONFLICT"


__all__ = [
    "BankMovementAlreadyReconciledError",
    "BankStatementConflictError",
    "FinanceDomainError",
    "FinanceScopeError",
    "FinanceVersionConflictError",
    "InstallmentMismatchError",
    "InvalidBankStatementError",
    "InvalidFinanceContractError",
    "InvalidPayableError",
    "InvalidPayableStateError",
    "InvalidProvisionalEntryError",
    "InvalidSegregationPolicyError",
    "InvalidTreasuryRuleError",
    "PayableApprovalRequiredError",
    "PayableConflictError",
    "PayableDivergenceBlockedError",
    "PaymentInstallmentIneligibleError",
    "SegregationOfDutiesViolation",
    "SodViolationError",
    "TreasuryConflictError",
    "TreasuryScopeError",
    "TreasurySodViolationError",
    "TreasuryVersionConflictError",
]
