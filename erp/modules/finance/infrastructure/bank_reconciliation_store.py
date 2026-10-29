"""Transactional PostgreSQL facade for bank-reconciliation API use cases."""

from collections.abc import Callable
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.application import (
    BankCandidateProvider,
    BankConciliationClassification,
    BankConciliationResult,
    BankConciliationService,
    BankMatchMode,
    BankMovementConciliation,
    BankMovementEntry,
    BankMovementPage,
    BankResolutionMode,
    BankStatementIngestionResult,
    BankStatementIngestionService,
    BankStatementPage,
    CompositeBankCandidateProvider,
    IngestBankStatement,
    MatchBankStatement,
    ResolveBankMovement,
    UploadBankStatement,
)
from erp.modules.finance.domain import (
    BankMovementStatus,
    BankReconciliationPolicy,
    BankStatement,
    BankTransactionKind,
    FinanceDomainError,
    ReconciliationDecision,
    ReconciliationReason,
    ReconciliationStatus,
)
from erp.modules.finance.infrastructure.bank_reconciliation_candidates import (
    PayableBankCandidateProvider,
)
from erp.modules.finance.infrastructure.bank_reconciliation_event_candidates import (
    EventBankCandidateProvider,
)
from erp.modules.finance.infrastructure.bank_reconciliation_events import (
    publish_reconciled_movements,
)
from erp.modules.finance.infrastructure.bank_statement_repository import (
    BankStatementRepository,
)
from erp.modules.finance.infrastructure.bank_statements import BankStatementParserRegistry
from erp.platform.database import Database
from erp.platform.errors import ApplicationError, ErrorDetail

CandidateProviderFactory = Callable[[AsyncSession, UUID], BankCandidateProvider]


class PostgresBankReconciliationStore:
    """Own transactions across parsing, statements and reconciliation evidence."""

    def __init__(
        self,
        database: Database,
        *,
        candidate_provider_factory: CandidateProviderFactory | None = None,
    ) -> None:
        self._database = database
        self._parsers = BankStatementParserRegistry()
        self._candidate_provider_factory = (
            candidate_provider_factory or _payable_candidate_provider
        )

    async def upload(
        self,
        command: UploadBankStatement,
        *,
        actor_id: UUID,
    ) -> BankStatementIngestionResult:
        async with self._database.session() as session, session.begin():
            try:
                return await BankStatementIngestionService(
                    self._parsers,
                    BankStatementRepository(session, company_id=command.company_id),
                ).ingest(
                    IngestBankStatement(
                        company_id=command.company_id,
                        bank_account_id=command.bank_account_id,
                        source=command.source,
                        content=command.content,
                        actor_id=actor_id,
                        original_file_name=command.original_file_name,
                        bank_code=command.bank_code,
                        account_reference=command.account_reference,
                    )
                )
            except FinanceDomainError as error:
                raise _domain_error(error) from error

    async def list(
        self,
        company_id: UUID,
        *,
        page: int,
        page_size: int,
        bank_account_id: UUID | None,
        period_from: date | None,
        period_to: date | None,
    ) -> BankStatementPage:
        async with self._database.session() as session:
            repository = BankStatementRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            try:
                values = await repository.list(
                    bank_account_id=bank_account_id,
                    period_from=period_from,
                    period_to=period_to,
                    limit=page_size,
                    offset=offset,
                )
                remaining = await repository.list(
                    bank_account_id=bank_account_id,
                    period_from=period_from,
                    period_to=period_to,
                    limit=1,
                    offset=offset + page_size,
                )
            except ValueError as error:
                raise _validation(str(error)) from error
            return BankStatementPage(
                items=values,
                page=page,
                page_size=page_size,
                has_more=bool(remaining),
            )

    async def get(self, company_id: UUID, statement_id: UUID) -> BankStatement | None:
        async with self._database.session() as session:
            return await BankStatementRepository(session, company_id=company_id).get(statement_id)

    async def list_movements(
        self,
        company_id: UUID,
        *,
        status: BankMovementStatus | None,
        statement_id: UUID | None,
        page: int,
        page_size: int,
    ) -> BankMovementPage:
        async with self._database.session() as session:
            repository = BankStatementRepository(session, company_id=company_id)
            offset = (page - 1) * page_size
            try:
                values = await repository.list_movements(
                    status=status,
                    statement_id=statement_id,
                    limit=page_size,
                    offset=offset,
                )
                remaining = await repository.list_movements(
                    status=status,
                    statement_id=statement_id,
                    limit=1,
                    offset=offset + page_size,
                )
            except ValueError as error:
                raise _validation(str(error)) from error
            return BankMovementPage(
                items=tuple(
                    BankMovementEntry(statement_id=owner_id, movement=movement)
                    for owner_id, movement in values
                ),
                page=page,
                page_size=page_size,
                has_more=bool(remaining),
            )

    async def match(
        self,
        command: MatchBankStatement,
        *,
        actor_id: UUID,
    ) -> BankConciliationResult:
        async with self._database.session() as session, session.begin():
            repository = BankStatementRepository(session, company_id=command.company_id)
            statement = await _required_statement(repository, command.statement_id)
            _require_version(statement.version, command.expected_version)
            service = BankConciliationService(
                repository,
                self._candidate_provider_factory(session, command.company_id),
            )
            try:
                if command.mode is BankMatchMode.SIMULATE:
                    return await service.simulate(command.statement_id)
                result = await service.reconcile(
                    command.statement_id,
                    actor_id=actor_id,
                    occurred_at=command.occurred_at,
                )
                await publish_reconciled_movements(
                    session,
                    before=statement,
                    result=result,
                )
                return result
            except FinanceDomainError as error:
                raise _domain_error(error) from error

    async def resolve(
        self,
        command: ResolveBankMovement,
        *,
        actor_id: UUID,
    ) -> BankConciliationResult:
        async with self._database.session() as session, session.begin():
            repository = BankStatementRepository(session, company_id=command.company_id)
            statement = await _required_statement(repository, command.statement_id)
            _require_version(statement.version, command.expected_version)
            movement = next(
                (value for value in statement.movements if value.id == command.movement_id),
                None,
            )
            if movement is None:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Bank movement not found.",
                    status_code=404,
                )
            if movement.status is BankMovementStatus.RECONCILED:
                raise ApplicationError(
                    code="BANK_MOVEMENT_ALREADY_RECONCILED",
                    message="Bank movement is already reconciled.",
                    status_code=409,
                )
            if command.mode is BankResolutionMode.DIRECT_ENTRY:
                classification = _direct_classification(movement.kind)
                if classification is None:
                    raise ApplicationError(
                        code="DIRECT_ENTRY_NOT_ALLOWED",
                        message="Only bank fees, interest and taxes may be classified directly.",
                        status_code=409,
                    )
                _justification(command.justification)
                return BankConciliationResult(
                    statement,
                    (
                        BankMovementConciliation(
                            movement.id,
                            classification,
                            None,
                        ),
                    ),
                )
            if command.candidate_id is None:
                raise _validation("candidate_id is required for match resolutions.")
            provider = self._candidate_provider_factory(session, command.company_id)
            candidates = await provider.candidates_for(movement)
            selected = next(
                (
                    value
                    for value in candidates
                    if value.candidate.reference_id == command.candidate_id
                ),
                None,
            )
            if selected is None:
                raise ApplicationError(
                    code="MATCH_CANDIDATE_NOT_FOUND",
                    message="Financial match candidate not found.",
                    status_code=404,
                )
            suggestion = BankReconciliationPolicy().evaluate(movement, selected.candidate)
            forced = command.mode is BankResolutionMode.FORCE_MATCH
            if not forced and suggestion.status is not ReconciliationStatus.MATCHED:
                raise ApplicationError(
                    code="MATCH_CONFLICT",
                    message="Candidate does not satisfy automatic reconciliation rules.",
                    status_code=409,
                    details=[ErrorDetail(message=suggestion.reason.value)],
                )
            justification = _justification(command.justification) if forced else None
            score = suggestion.score
            decision = ReconciliationDecision(
                movement_id=movement.id,
                status=ReconciliationStatus.MATCHED,
                reason=ReconciliationReason.MATCHED,
                candidate_id=selected.candidate.reference_id,
                score=score,
            )
            updated = statement.apply(decision, reconciled_at=command.occurred_at)
            try:
                await repository.save(
                    updated,
                    actor_id=actor_id,
                    expected_version=command.expected_version,
                    conciliation_metadata={
                        movement.id: {
                            "resolution": command.mode.value,
                            "candidate_source": selected.source.value,
                            "forced": forced,
                            "justification": justification,
                            "original_reason": suggestion.reason.value,
                        }
                    },
                )
            except FinanceDomainError as error:
                raise _domain_error(error) from error
            result = BankConciliationResult(
                updated,
                (
                    BankMovementConciliation(
                        movement_id=movement.id,
                        classification=BankConciliationClassification.RECONCILED,
                        reason=ReconciliationReason.MATCHED,
                        candidate_id=selected.candidate.reference_id,
                        candidate_source=selected.source,
                        candidate_count=len(candidates),
                    ),
                ),
            )
            await publish_reconciled_movements(
                session,
                before=statement,
                result=result,
            )
            return result


def _payable_candidate_provider(
    session: AsyncSession,
    company_id: UUID,
) -> BankCandidateProvider:
    return CompositeBankCandidateProvider(
        PayableBankCandidateProvider(session, company_id=company_id),
        EventBankCandidateProvider(session, company_id=company_id),
    )


async def _required_statement(
    repository: BankStatementRepository,
    statement_id: UUID,
) -> BankStatement:
    statement = await repository.get(statement_id)
    if statement is None:
        raise ApplicationError(
            code="RESOURCE_NOT_FOUND",
            message="Bank statement not found.",
            status_code=404,
        )
    return statement


def _require_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise ApplicationError(
            code="VERSION_CONFLICT",
            message="The bank statement was changed by another transaction.",
            status_code=409,
        )


def _justification(value: str | None) -> str:
    if not isinstance(value, str):
        raise _validation("A justification is required for this resolution.")
    normalized = " ".join(value.split())
    if not 10 <= len(normalized) <= 500:
        raise _validation("Justification must contain between 10 and 500 characters.")
    return normalized


def _direct_classification(
    kind: BankTransactionKind,
) -> BankConciliationClassification | None:
    return {
        BankTransactionKind.BANK_FEE: BankConciliationClassification.DIRECT_BANK_FEE,
        BankTransactionKind.INTEREST: BankConciliationClassification.DIRECT_INTEREST,
        BankTransactionKind.TAX: BankConciliationClassification.DIRECT_TAX,
    }.get(kind)


def _validation(message: str) -> ApplicationError:
    return ApplicationError(code="VALIDATION_ERROR", message=message, status_code=422)


def _domain_error(error: FinanceDomainError) -> ApplicationError:
    status = 409 if error.code in {"VERSION_CONFLICT", "BANK_STATEMENT_CONFLICT"} else 422
    return ApplicationError(
        code=error.code,
        message="Invalid bank reconciliation operation.",
        status_code=status,
        details=[ErrorDetail(message=str(error))],
    )


__all__ = ["PostgresBankReconciliationStore"]
