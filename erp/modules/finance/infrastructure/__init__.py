"""M12 persistence adapters."""

from erp.modules.finance.infrastructure.bank_reconciliation_candidates import (
    PayableBankCandidateProvider,
)
from erp.modules.finance.infrastructure.bank_reconciliation_event_candidates import (
    EventBankCandidateProvider,
)
from erp.modules.finance.infrastructure.bank_reconciliation_event_consumer import (
    BANK_RECONCILIATION_EVENT_CONSUMER,
    BankReconciliationEventConsumer,
)
from erp.modules.finance.infrastructure.bank_reconciliation_event_model import (
    BankReconciliationCandidateModel,
    BankReconciliationSourceCursorModel,
)
from erp.modules.finance.infrastructure.bank_reconciliation_event_state import (
    BankCandidateProjection,
    accept_bank_reconciliation_cursor,
    deactivate_event_candidate,
    flag_reversed_reconciliations,
    reevaluate_pending_statements,
    upsert_event_candidate,
)
from erp.modules.finance.infrastructure.bank_reconciliation_events import (
    BANK_MOVEMENT_RECONCILED,
    BANK_RECONCILIATION_REVIEW_REQUIRED,
    publish_reconciled_movements,
    publish_reconciliation_review,
)
from erp.modules.finance.infrastructure.bank_reconciliation_store import (
    PostgresBankReconciliationStore,
)
from erp.modules.finance.infrastructure.bank_returns import (
    BankReturnAdapterRegistry,
    Cnab240ReturnParser,
    Cnab400ReturnParser,
    PixCallbackParser,
)
from erp.modules.finance.infrastructure.bank_statement_model import (
    BankMovementModel,
    BankStatementModel,
    ConciliationRecordModel,
    StatementImportAuditModel,
)
from erp.modules.finance.infrastructure.bank_statement_repository import (
    BankStatementRepository,
)
from erp.modules.finance.infrastructure.bank_statements import (
    BankStatementImportContext,
    BankStatementParserRegistry,
    CsvStatementLayout,
    CsvStatementParser,
    OfxStatementParser,
)
from erp.modules.finance.infrastructure.cash_flow_event_consumer import (
    CASH_FLOW_EVENT_CONSUMER,
    CashFlowEventConsumer,
)
from erp.modules.finance.infrastructure.cash_flow_event_model import (
    CashFlowRecompositionRequestModel,
    CashFlowSourceCursorModel,
)
from erp.modules.finance.infrastructure.cash_flow_event_state import (
    CASH_FLOW_PROJECTION_RECOMPOSED,
    CashFlowRecompositionWorker,
    accept_cash_flow_source_cursor,
    enqueue_cash_flow_recompositions,
)
from erp.modules.finance.infrastructure.cash_flow_model import (
    CashFlowAuditLogModel,
    CashFlowProjectionSnapshotModel,
    CashFlowScenarioDefinitionModel,
)
from erp.modules.finance.infrastructure.cash_flow_repository import (
    CashFlowProjectionRepository,
)
from erp.modules.finance.infrastructure.cash_flow_sources import (
    PostgresBankPositionProvider,
    PostgresPayableCommitmentProvider,
)
from erp.modules.finance.infrastructure.cash_flow_store import PostgresCashFlowStore
from erp.modules.finance.infrastructure.governance_consumer import (
    FINANCE_APPROVAL_CONSUMER,
    FINANCE_DIVERGENCE_CONSUMER,
    PayableApprovalDecisionConsumer,
    PayableDivergenceConsumer,
)
from erp.modules.finance.infrastructure.payable_governance_model import PayableGovernanceModel
from erp.modules.finance.infrastructure.payable_governance_repository import (
    PayableGovernanceRepository,
)
from erp.modules.finance.infrastructure.payable_model import (
    PayableInstallmentModel,
    PayableModel,
    ProvisionalEntryModel,
)
from erp.modules.finance.infrastructure.payable_repository import PayableRepository
from erp.modules.finance.infrastructure.payable_store import PostgresPayableStore
from erp.modules.finance.infrastructure.provisional_repository import (
    ProvisionalEntryRepository,
)
from erp.modules.finance.infrastructure.provisioning_consumer import (
    FINANCE_PAYABLE_PROVISIONING_CONSUMER,
    FISCAL_DOCUMENT_AUTHORIZED,
    FISCAL_DOCUMENT_CANCELLED,
    PURCHASE_ORDER_APPROVED,
    FiscalEventConsumer,
    PayableProvisioningConsumer,
    PayableProvisioningService,
)
from erp.modules.finance.infrastructure.remittance import (
    Cnab240RemittanceAdapter,
    Cnab400RemittanceAdapter,
    PixApiRemittanceAdapter,
    RemittanceAdapterRegistry,
)
from erp.modules.finance.infrastructure.treasury_event_consumer import (
    TREASURY_EVENT_CONSUMER,
    TreasuryEventConsumer,
)
from erp.modules.finance.infrastructure.treasury_event_model import (
    PaymentBatchReviewModel,
    TreasurySourceCursorModel,
)
from erp.modules.finance.infrastructure.treasury_event_state import (
    PAYMENT_BATCH_BLOCKED,
    PAYMENT_BATCH_REEVALUATION_CLEARED,
    PAYMENT_BATCH_REEVALUATION_REQUESTED,
    TreasuryAssessment,
    TreasuryReviewStatus,
    accept_treasury_source_cursor,
    apply_treasury_source_cursors,
    reassess_impacted_payment_batches,
    require_payment_batch_unblocked,
)
from erp.modules.finance.infrastructure.treasury_events import (
    PostgresPaymentBatchEventPublisher,
)
from erp.modules.finance.infrastructure.treasury_model import (
    BatchAuditLogModel,
    PaymentBatchItemModel,
    PaymentBatchModel,
)
from erp.modules.finance.infrastructure.treasury_repository import PaymentBatchRepository
from erp.modules.finance.infrastructure.treasury_store import PostgresTreasuryStore

__all__ = [
    "BANK_MOVEMENT_RECONCILED",
    "BANK_RECONCILIATION_EVENT_CONSUMER",
    "BANK_RECONCILIATION_REVIEW_REQUIRED",
    "CASH_FLOW_EVENT_CONSUMER",
    "CASH_FLOW_PROJECTION_RECOMPOSED",
    "FINANCE_APPROVAL_CONSUMER",
    "FINANCE_DIVERGENCE_CONSUMER",
    "FINANCE_PAYABLE_PROVISIONING_CONSUMER",
    "FISCAL_DOCUMENT_AUTHORIZED",
    "FISCAL_DOCUMENT_CANCELLED",
    "PAYMENT_BATCH_BLOCKED",
    "PAYMENT_BATCH_REEVALUATION_CLEARED",
    "PAYMENT_BATCH_REEVALUATION_REQUESTED",
    "PURCHASE_ORDER_APPROVED",
    "TREASURY_EVENT_CONSUMER",
    "BankCandidateProjection",
    "BankMovementModel",
    "BankReconciliationCandidateModel",
    "BankReconciliationEventConsumer",
    "BankReconciliationSourceCursorModel",
    "BankReturnAdapterRegistry",
    "BankStatementImportContext",
    "BankStatementModel",
    "BankStatementParserRegistry",
    "BankStatementRepository",
    "BatchAuditLogModel",
    "CashFlowAuditLogModel",
    "CashFlowEventConsumer",
    "CashFlowProjectionRepository",
    "CashFlowProjectionSnapshotModel",
    "CashFlowRecompositionRequestModel",
    "CashFlowRecompositionWorker",
    "CashFlowScenarioDefinitionModel",
    "CashFlowSourceCursorModel",
    "Cnab240RemittanceAdapter",
    "Cnab240ReturnParser",
    "Cnab400RemittanceAdapter",
    "Cnab400ReturnParser",
    "ConciliationRecordModel",
    "CsvStatementLayout",
    "CsvStatementParser",
    "EventBankCandidateProvider",
    "FiscalEventConsumer",
    "OfxStatementParser",
    "PayableApprovalDecisionConsumer",
    "PayableBankCandidateProvider",
    "PayableDivergenceConsumer",
    "PayableGovernanceModel",
    "PayableGovernanceRepository",
    "PayableInstallmentModel",
    "PayableModel",
    "PayableProvisioningConsumer",
    "PayableProvisioningService",
    "PayableRepository",
    "PaymentBatchItemModel",
    "PaymentBatchModel",
    "PaymentBatchRepository",
    "PaymentBatchReviewModel",
    "PixApiRemittanceAdapter",
    "PixCallbackParser",
    "PostgresBankPositionProvider",
    "PostgresBankReconciliationStore",
    "PostgresCashFlowStore",
    "PostgresPayableCommitmentProvider",
    "PostgresPayableStore",
    "PostgresPaymentBatchEventPublisher",
    "PostgresTreasuryStore",
    "ProvisionalEntryModel",
    "ProvisionalEntryRepository",
    "RemittanceAdapterRegistry",
    "StatementImportAuditModel",
    "TreasuryAssessment",
    "TreasuryEventConsumer",
    "TreasuryReviewStatus",
    "TreasurySourceCursorModel",
    "accept_bank_reconciliation_cursor",
    "accept_cash_flow_source_cursor",
    "accept_treasury_source_cursor",
    "apply_treasury_source_cursors",
    "deactivate_event_candidate",
    "enqueue_cash_flow_recompositions",
    "flag_reversed_reconciliations",
    "publish_reconciled_movements",
    "publish_reconciliation_review",
    "reassess_impacted_payment_batches",
    "reevaluate_pending_statements",
    "require_payment_batch_unblocked",
    "upsert_event_candidate",
]
