"""Framework-neutral ingestion and automatic bank reconciliation use cases."""

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from erp.modules.finance.domain import (
    BankMovement,
    BankMovementStatus,
    BankReconciliationPolicy,
    BankStatement,
    BankStatementSource,
    BankTransactionKind,
    FinancialReconciliationCandidate,
    InvalidBankStatementError,
    ReconciliationDecision,
    ReconciliationReason,
    ReconciliationStatus,
    ReconciliationSuggestion,
)


@dataclass(frozen=True, slots=True)
class BankStatementImportContext:
    """Trusted tenant and bank-account metadata for an external parser."""

    statement_id: UUID
    company_id: UUID
    bank_account_id: UUID
    imported_at: datetime
    bank_code: str | None = None
    account_reference: str | None = None


class BankStatementParserPort(Protocol):
    def parse(
        self,
        source: BankStatementSource,
        content: bytes,
        *,
        context: BankStatementImportContext,
    ) -> BankStatement: ...


class BankStatementStore(Protocol):
    async def get(self, statement_id: UUID) -> BankStatement | None: ...

    async def get_by_hash(
        self,
        *,
        bank_account_id: UUID,
        source_hash: str,
    ) -> BankStatement | None: ...

    async def add_idempotent(
        self,
        statement: BankStatement,
        *,
        actor_id: UUID,
        original_file_name: str | None,
        file_size_bytes: int,
    ) -> tuple[BankStatement, bool]: ...

    async def save(
        self,
        statement: BankStatement,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
        conciliation_metadata: Mapping[UUID, Mapping[str, object]] | None = None,
    ) -> BankStatement: ...


@dataclass(frozen=True, slots=True)
class IngestBankStatement:
    company_id: UUID
    bank_account_id: UUID
    source: BankStatementSource
    content: bytes
    actor_id: UUID
    original_file_name: str | None = None
    bank_code: str | None = None
    account_reference: str | None = None


@dataclass(frozen=True, slots=True)
class BankStatementIngestionResult:
    statement: BankStatement
    idempotency_replayed: bool


class BankStatementIngestionService:
    def __init__(
        self,
        parser: BankStatementParserPort,
        store: BankStatementStore,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._parser = parser
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or uuid4

    async def ingest(self, command: IngestBankStatement) -> BankStatementIngestionResult:
        _ingestion_command(command)
        source_hash = hashlib.sha256(command.content).hexdigest()
        existing = await self._store.get_by_hash(
            bank_account_id=command.bank_account_id,
            source_hash=source_hash,
        )
        if existing is not None:
            return BankStatementIngestionResult(existing, True)
        imported_at = self._clock()
        if imported_at.tzinfo is None or imported_at.utcoffset() is None:
            raise InvalidBankStatementError("Ingestion clock must return timezone-aware values.")
        statement = self._parser.parse(
            command.source,
            command.content,
            context=BankStatementImportContext(
                statement_id=self._id_factory(),
                company_id=command.company_id,
                bank_account_id=command.bank_account_id,
                imported_at=imported_at,
                bank_code=command.bank_code,
                account_reference=command.account_reference,
            ),
        )
        if statement.source_hash != source_hash:
            raise InvalidBankStatementError("Parser returned a mismatched source hash.")
        persisted, replayed = await self._store.add_idempotent(
            statement,
            actor_id=command.actor_id,
            original_file_name=command.original_file_name,
            file_size_bytes=len(command.content),
        )
        return BankStatementIngestionResult(persisted, replayed)


class BankCandidateSource(StrEnum):
    PAYABLE_M12 = "PAYABLE_M12"
    TREASURY_M12 = "TREASURY_M12"
    RECEIVABLE_M13 = "RECEIVABLE_M13"


@dataclass(frozen=True, slots=True)
class BankMatchCandidate:
    candidate: FinancialReconciliationCandidate
    source: BankCandidateSource

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, FinancialReconciliationCandidate):
            raise InvalidBankStatementError("candidate must be a FinancialReconciliationCandidate.")
        if not isinstance(self.source, BankCandidateSource):
            raise InvalidBankStatementError("source must be a BankCandidateSource.")


@dataclass(frozen=True, slots=True)
class BankCandidateOption:
    """Explainable candidate presented to a human reconciliation decision."""

    match: BankMatchCandidate
    suggestion: ReconciliationSuggestion

    def __post_init__(self) -> None:
        if not isinstance(self.match, BankMatchCandidate):
            raise InvalidBankStatementError("match must be a BankMatchCandidate.")
        if not isinstance(self.suggestion, ReconciliationSuggestion):
            raise InvalidBankStatementError("suggestion must be a ReconciliationSuggestion.")


class BankCandidateProvider(Protocol):
    async def candidates_for(self, movement: BankMovement) -> tuple[BankMatchCandidate, ...]: ...


class CompositeBankCandidateProvider:
    """Compose M12 and future M13 adapters without cross-context imports."""

    def __init__(self, *providers: BankCandidateProvider) -> None:
        if not providers:
            raise ValueError("At least one bank candidate provider is required.")
        self._providers = providers

    async def candidates_for(self, movement: BankMovement) -> tuple[BankMatchCandidate, ...]:
        values: dict[UUID, BankMatchCandidate] = {}
        for provider in self._providers:
            for value in await provider.candidates_for(movement):
                existing = values.get(value.candidate.reference_id)
                if existing is not None and existing != value:
                    raise InvalidBankStatementError(
                        "Candidate providers returned conflicting financial references."
                    )
                values[value.candidate.reference_id] = value
        return tuple(values[key] for key in sorted(values, key=str))


class BankConciliationClassification(StrEnum):
    RECONCILED = "RECONCILED"
    PENDING = "PENDING"
    AMBIGUOUS = "AMBIGUOUS"
    DIRECT_BANK_FEE = "DIRECT_BANK_FEE"
    DIRECT_INTEREST = "DIRECT_INTEREST"
    DIRECT_TAX = "DIRECT_TAX"


@dataclass(frozen=True, slots=True)
class BankMovementConciliation:
    movement_id: UUID
    classification: BankConciliationClassification
    reason: ReconciliationReason | None
    candidate_id: UUID | None = None
    candidate_source: BankCandidateSource | None = None
    candidate_count: int = 0


@dataclass(frozen=True, slots=True)
class BankConciliationResult:
    statement: BankStatement
    outcomes: tuple[BankMovementConciliation, ...]

    @property
    def reconciled_count(self) -> int:
        return sum(
            value.classification is BankConciliationClassification.RECONCILED
            for value in self.outcomes
        )


class BankConciliationService:
    def __init__(
        self,
        store: BankStatementStore,
        candidates: BankCandidateProvider,
        policy: BankReconciliationPolicy | None = None,
    ) -> None:
        self._store = store
        self._candidates = candidates
        self._policy = policy or BankReconciliationPolicy()

    async def reconcile(
        self,
        statement_id: UUID,
        *,
        actor_id: UUID,
        occurred_at: datetime,
    ) -> BankConciliationResult:
        _nonzero_uuid(statement_id, "statement_id")
        _nonzero_uuid(actor_id, "actor_id")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise InvalidBankStatementError("occurred_at must be timezone-aware.")
        statement = await self._store.get(statement_id)
        if statement is None:
            raise InvalidBankStatementError("Bank statement was not found in the company scope.")
        outcomes, decisions = await self._evaluate(statement)
        if decisions:
            statement = statement.apply_many(tuple(decisions), reconciled_at=occurred_at)
            await self._store.save(statement, actor_id=actor_id)
        return BankConciliationResult(statement, outcomes)

    async def simulate(self, statement_id: UUID) -> BankConciliationResult:
        _nonzero_uuid(statement_id, "statement_id")
        statement = await self._store.get(statement_id)
        if statement is None:
            raise InvalidBankStatementError("Bank statement was not found in the company scope.")
        outcomes, _ = await self._evaluate(statement)
        return BankConciliationResult(statement, outcomes)

    async def _evaluate(
        self,
        statement: BankStatement,
    ) -> tuple[tuple[BankMovementConciliation, ...], list[ReconciliationDecision]]:
        decisions: list[ReconciliationDecision] = []
        outcomes: list[BankMovementConciliation] = []
        for movement in statement.movements:
            if movement.status is BankMovementStatus.RECONCILED:
                continue
            direct = _direct_classification(movement.kind)
            if direct is not None:
                outcomes.append(BankMovementConciliation(movement.id, direct, None))
                continue
            candidates = await self._candidates.candidates_for(movement)
            candidate_by_id = {value.candidate.reference_id: value for value in candidates}
            decision = self._policy.best_match(
                movement,
                tuple(value.candidate for value in candidates),
            )
            source = (
                candidate_by_id[decision.candidate_id].source
                if decision.candidate_id is not None
                else None
            )
            classification = {
                ReconciliationStatus.MATCHED: BankConciliationClassification.RECONCILED,
                ReconciliationStatus.PENDING: BankConciliationClassification.PENDING,
                ReconciliationStatus.AMBIGUOUS: BankConciliationClassification.AMBIGUOUS,
            }[decision.status]
            outcomes.append(
                BankMovementConciliation(
                    movement_id=movement.id,
                    classification=classification,
                    reason=decision.reason,
                    candidate_id=decision.candidate_id,
                    candidate_source=source,
                    candidate_count=len(candidates),
                )
            )
            if decision.status is ReconciliationStatus.MATCHED:
                decisions.append(decision)
        return tuple(outcomes), decisions


def _direct_classification(
    kind: BankTransactionKind,
) -> BankConciliationClassification | None:
    return {
        BankTransactionKind.BANK_FEE: BankConciliationClassification.DIRECT_BANK_FEE,
        BankTransactionKind.INTEREST: BankConciliationClassification.DIRECT_INTEREST,
        BankTransactionKind.TAX: BankConciliationClassification.DIRECT_TAX,
    }.get(kind)


def _ingestion_command(command: IngestBankStatement) -> None:
    if not isinstance(command, IngestBankStatement):
        raise TypeError("command must be an IngestBankStatement.")
    _nonzero_uuid(command.company_id, "company_id")
    _nonzero_uuid(command.bank_account_id, "bank_account_id")
    _nonzero_uuid(command.actor_id, "actor_id")
    if not isinstance(command.source, BankStatementSource):
        raise InvalidBankStatementError("source must be a BankStatementSource.")
    if not isinstance(command.content, bytes) or not command.content:
        raise InvalidBankStatementError("Bank statement content cannot be empty.")


def _nonzero_uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidBankStatementError(f"{field} must be a non-zero UUID.")
    return value


__all__ = [
    "BankCandidateOption",
    "BankCandidateProvider",
    "BankCandidateSource",
    "BankConciliationClassification",
    "BankConciliationResult",
    "BankConciliationService",
    "BankMatchCandidate",
    "BankMovementConciliation",
    "BankStatementImportContext",
    "BankStatementIngestionResult",
    "BankStatementIngestionService",
    "BankStatementParserPort",
    "BankStatementStore",
    "CompositeBankCandidateProvider",
    "IngestBankStatement",
]
