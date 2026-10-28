"""Pure bank-statement and deterministic reconciliation rule coverage."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.domain import (
    BankMovement,
    BankMovementAlreadyReconciledError,
    BankMovementDirection,
    BankMovementStatus,
    BankReconciliationPolicy,
    BankStatement,
    BankStatementSource,
    BankStatementStatus,
    BankTransactionKind,
    FinanceScopeError,
    FinancialReconciliationCandidate,
    InvalidBankStatementError,
    ReconciliationDecision,
    ReconciliationReason,
    ReconciliationStatus,
    ReconciliationTolerance,
)

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


def _movement(
    *,
    company_id: UUID | None = None,
    bank_account_id: UUID | None = None,
    movement_id: UUID | None = None,
    external_id: str = "FIT-180-1",
    booked_on: date = date(2026, 10, 27),
    amount: Decimal = Decimal("100.00"),
    direction: BankMovementDirection = BankMovementDirection.DEBIT,
    document: str | None = "NF-12345",
) -> BankMovement:
    return BankMovement(
        id=movement_id or uuid4(),
        company_id=company_id or uuid4(),
        bank_account_id=bank_account_id or uuid4(),
        external_id=external_id,
        booked_on=booked_on,
        amount=amount,
        direction=direction,
        kind=BankTransactionKind.PAYMENT,
        description="Pagamento fornecedor",
        document_number=document,
    )


def _candidate(
    movement: BankMovement,
    *,
    reference_id: UUID | None = None,
    company_id: UUID | None = None,
    expected_on: date | None = None,
    amount: Decimal | None = None,
    direction: BankMovementDirection | None = None,
    document: str | None = "NF-12345",
) -> FinancialReconciliationCandidate:
    return FinancialReconciliationCandidate(
        reference_id=reference_id or uuid4(),
        company_id=company_id or movement.company_id,
        expected_on=expected_on or movement.booked_on,
        amount=amount or movement.amount,
        direction=direction or movement.direction,
        document_number=document,
    )


def _statement(*movements: BankMovement) -> BankStatement:
    first = movements[0]
    return BankStatement(
        id=uuid4(),
        company_id=first.company_id,
        bank_account_id=first.bank_account_id,
        bank_code="001",
        account_reference="****1234",
        period_start=min(item.booked_on for item in movements),
        period_end=max(item.booked_on for item in movements),
        imported_at=NOW,
        source=BankStatementSource.OFX,
        source_hash="a" * 64,
        movements=tuple(movements),
    )


def test_statement_is_immutable_and_tracks_pending_partial_and_complete_status() -> None:
    company_id = uuid4()
    bank_account_id = uuid4()
    first = _movement(company_id=company_id, bank_account_id=bank_account_id)
    second = _movement(
        company_id=company_id,
        bank_account_id=bank_account_id,
        external_id="FIT-180-2",
        movement_id=uuid4(),
        booked_on=date(2026, 10, 28),
        amount=Decimal("25.00"),
    )
    statement = _statement(first, second)
    assert statement.status is BankStatementStatus.PENDING
    assert statement.movements_on(date(2026, 10, 27)) == (first,)
    assert first.signed_amount == Decimal("-100.00")
    credit = replace(first, direction=BankMovementDirection.CREDIT)
    assert credit.signed_amount == Decimal("100.00")

    first_decision = BankReconciliationPolicy().best_match(first, (_candidate(first),))
    partial = statement.apply(first_decision, reconciled_at=NOW)
    assert statement.status is BankStatementStatus.PENDING
    assert partial.status is BankStatementStatus.PARTIALLY_RECONCILED

    second_decision = BankReconciliationPolicy().best_match(second, (_candidate(second),))
    complete = partial.apply(second_decision, reconciled_at=NOW)
    assert complete.status is BankStatementStatus.RECONCILED
    assert complete.movements[0].status is BankMovementStatus.RECONCILED

    with pytest.raises(BankMovementAlreadyReconciledError):
        complete.apply(first_decision, reconciled_at=NOW)


def test_statement_validates_scope_period_uniqueness_hash_and_balances() -> None:
    movement = _movement(direction=BankMovementDirection.CREDIT)
    base = _statement(movement)
    balanced = replace(
        base,
        opening_balance=Decimal("25.00"),
        closing_balance=Decimal("125.00"),
    )
    assert balanced.closing_balance == Decimal("125.00")

    invalid_changes = (
        {"id": UUID(int=0)},
        {"bank_code": " "},
        {"period_start": "2026-10-27"},
        {"period_start": date(2026, 10, 29)},
        {"imported_at": NOW.replace(tzinfo=None)},
        {"source": "OFX"},
        {"source_hash": "not-a-hash"},
        {"movements": ()},
        {"movements": (movement, movement)},
        {"opening_balance": Decimal("25.00"), "closing_balance": Decimal("124.98")},
    )
    for changes in invalid_changes:
        with pytest.raises(InvalidBankStatementError):
            replace(base, **changes)

    other_scope = replace(movement, company_id=uuid4())
    outside_period = replace(movement, booked_on=date(2026, 10, 29))
    with pytest.raises(InvalidBankStatementError, match="share statement"):
        replace(base, movements=(other_scope,))
    with pytest.raises(InvalidBankStatementError, match="inside the statement period"):
        replace(base, movements=(outside_period,))
    with pytest.raises(InvalidBankStatementError, match="must contain BankMovement"):
        replace(base, movements=(cast(BankMovement, object()),))
    with pytest.raises(InvalidBankStatementError, match="day must be a date"):
        base.movements_on(cast(date, "2026-10-27"))


def test_statement_only_applies_complete_unambiguous_decisions_for_its_movement() -> None:
    movement = _movement()
    statement = _statement(movement)
    pending = ReconciliationDecision(
        movement.id,
        ReconciliationStatus.PENDING,
        ReconciliationReason.NO_CANDIDATE,
    )
    with pytest.raises(InvalidBankStatementError, match="unambiguous"):
        statement.apply(pending, reconciled_at=NOW)
    incomplete = ReconciliationDecision(
        movement.id,
        ReconciliationStatus.MATCHED,
        ReconciliationReason.MATCHED,
    )
    with pytest.raises(InvalidBankStatementError, match="candidate and score"):
        statement.apply(incomplete, reconciled_at=NOW)
    foreign = replace(
        incomplete,
        movement_id=uuid4(),
        candidate_id=uuid4(),
        score=Decimal("1"),
    )
    with pytest.raises(InvalidBankStatementError, match="does not belong"):
        statement.apply(foreign, reconciled_at=NOW)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"external_id": ""}, "external_id"),
        ({"external_id": None}, "must be text"),
        ({"booked_on": "2026-10-27"}, "booked_on"),
        ({"amount": Decimal("0.00")}, "positive"),
        ({"amount": Decimal("1.001")}, "two decimals"),
        ({"amount": Decimal("1E+999999")}, "unsupported precision"),
        ({"direction": "DEBIT"}, "direction"),
        ({"kind": "PAYMENT"}, "kind"),
        ({"description": ""}, "description"),
        ({"status": "PENDING"}, "status"),
        ({"matched_reference_id": uuid4()}, "pending movement"),
    ],
)
def test_movement_invariants(changes: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidBankStatementError, match=message):
        replace(_movement(), **cast(Any, changes))


def test_reconciled_movement_requires_complete_typed_evidence() -> None:
    movement = _movement()
    with pytest.raises(InvalidBankStatementError, match="complete evidence"):
        replace(movement, status=BankMovementStatus.RECONCILED)
    with pytest.raises(InvalidBankStatementError, match="between 0 and 1"):
        movement.reconcile(reference_id=uuid4(), reconciled_at=NOW, score=Decimal("1.1"))
    with pytest.raises(InvalidBankStatementError, match="timezone-aware"):
        movement.reconcile(
            reference_id=uuid4(),
            reconciled_at=NOW.replace(tzinfo=None),
            score=Decimal("1"),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"reference_id": UUID(int=0)},
        {"expected_on": "2026-10-27"},
        {"amount": Decimal("NaN")},
        {"direction": "DEBIT"},
        {"document_number": ""},
    ],
)
def test_candidate_invariants(changes: dict[str, object]) -> None:
    movement = _movement()
    with pytest.raises(InvalidBankStatementError):
        replace(_candidate(movement), **cast(Any, changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": Decimal("-0.01")},
        {"amount": Decimal("0.001")},
        {"date_days": -1},
        {"date_days": 32},
        {"date_days": True},
        {"document_similarity": Decimal("1.1")},
        {"auto_match_score": Decimal("NaN")},
    ],
)
def test_tolerance_invariants(changes: dict[str, object]) -> None:
    with pytest.raises(InvalidBankStatementError):
        replace(ReconciliationTolerance(), **cast(Any, changes))


def test_policy_explains_each_blocking_dimension_and_scope() -> None:
    movement = _movement()
    policy = BankReconciliationPolicy()
    cases = (
        (
            _candidate(movement, direction=BankMovementDirection.CREDIT),
            ReconciliationReason.DIRECTION_MISMATCH,
        ),
        (
            _candidate(movement, amount=Decimal("100.02")),
            ReconciliationReason.AMOUNT_MISMATCH,
        ),
        (
            _candidate(movement, expected_on=date(2026, 10, 30)),
            ReconciliationReason.DATE_MISMATCH,
        ),
        (
            _candidate(movement, document="OTHER-999"),
            ReconciliationReason.DOCUMENT_MISMATCH,
        ),
    )
    for candidate, reason in cases:
        result = policy.evaluate(movement, candidate)
        assert result.status is ReconciliationStatus.PENDING
        assert result.reason is reason

    with pytest.raises(FinanceScopeError):
        policy.evaluate(movement, _candidate(movement, company_id=uuid4()))
    with pytest.raises(InvalidBankStatementError, match="typed movement"):
        policy.evaluate(cast(BankMovement, object()), _candidate(movement))


def test_policy_accepts_exact_and_tolerated_matches_but_honors_score_threshold() -> None:
    movement = _movement()
    exact = BankReconciliationPolicy().evaluate(movement, _candidate(movement))
    assert exact.status is ReconciliationStatus.MATCHED
    assert exact.reason is ReconciliationReason.MATCHED
    assert exact.score == Decimal("1.0000")
    assert exact.amount_delta == Decimal("0.00")
    assert exact.date_delta_days == 0
    assert exact.document_similarity == Decimal("1.0000")

    tolerant_policy = BankReconciliationPolicy(
        ReconciliationTolerance(
            amount=Decimal("0.02"),
            date_days=2,
            document_similarity=Decimal("0.75"),
            auto_match_score=Decimal("0.50"),
        )
    )
    tolerated = tolerant_policy.evaluate(
        movement,
        _candidate(
            movement,
            amount=Decimal("100.01"),
            expected_on=date(2026, 10, 28),
            document="NF1234S",
        ),
    )
    assert tolerated.status is ReconciliationStatus.MATCHED
    assert Decimal("0.50") <= tolerated.score < Decimal("1")

    strict_score = BankReconciliationPolicy(
        ReconciliationTolerance(auto_match_score=Decimal("0.95"))
    ).evaluate(movement, _candidate(movement, document=None))
    assert strict_score.reason is ReconciliationReason.SCORE_BELOW_THRESHOLD


def test_policy_treats_missing_documents_neutrally_and_zero_tolerance_deterministically() -> None:
    movement = _movement(document=None)
    exact = BankReconciliationPolicy(
        ReconciliationTolerance(amount=Decimal("0.00"), date_days=0)
    ).evaluate(movement, _candidate(movement, document=None))
    one_missing = BankReconciliationPolicy().evaluate(
        replace(movement, document_number="DOC-1"),
        _candidate(movement, document=None),
    )
    assert exact.document_similarity == Decimal("0.5000")
    assert exact.status is ReconciliationStatus.MATCHED
    assert one_missing.document_similarity == Decimal("0.0000")
    assert one_missing.status is ReconciliationStatus.MATCHED

    punctuation_only = BankReconciliationPolicy().evaluate(
        replace(movement, document_number="---"),
        _candidate(movement, document="..."),
    )
    assert punctuation_only.document_similarity == Decimal("0.0000")
    assert punctuation_only.reason is ReconciliationReason.DOCUMENT_MISMATCH


def test_best_match_is_deterministic_and_refuses_ambiguity() -> None:
    movement = _movement()
    policy = BankReconciliationPolicy()
    no_match = policy.best_match(
        movement,
        (_candidate(movement, amount=Decimal("200.00")),),
    )
    assert no_match.status is ReconciliationStatus.PENDING
    assert no_match.reason is ReconciliationReason.NO_CANDIDATE

    same_score = (
        _candidate(movement, reference_id=uuid4()),
        _candidate(movement, reference_id=uuid4()),
    )
    ambiguous = policy.best_match(movement, same_score)
    assert ambiguous.status is ReconciliationStatus.AMBIGUOUS
    assert ambiguous.reason is ReconciliationReason.AMBIGUOUS_CANDIDATES
    assert ambiguous.candidate_id is None

    weaker = _candidate(movement, document=None)
    winner = _candidate(movement, reference_id=uuid4())
    matched = policy.best_match(movement, (weaker, winner))
    assert matched.status is ReconciliationStatus.MATCHED
    assert matched.candidate_id == winner.reference_id
    assert matched.score == Decimal("1.0000")
