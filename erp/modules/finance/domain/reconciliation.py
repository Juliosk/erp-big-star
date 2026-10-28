"""Pure M12 bank-statement aggregates and deterministic reconciliation rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from enum import StrEnum
from uuid import UUID

from erp.modules.finance.domain.exceptions import (
    BankMovementAlreadyReconciledError,
    FinanceScopeError,
    InvalidBankStatementError,
)

_CENT = Decimal("0.01")
_SCORE = Decimal("0.0001")


def _uuid(value: UUID, field: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise InvalidBankStatementError(f"{field} must be a non-zero UUID.")
    return value


def _text(value: str, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidBankStatementError(f"{field} must be text.")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise InvalidBankStatementError(f"{field} must contain between 1 and {maximum} characters.")
    return normalized


def _optional_text(value: str | None, field: str, *, maximum: int) -> str | None:
    return None if value is None else _text(value, field, maximum=maximum)


def _money(value: Decimal, field: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise InvalidBankStatementError(f"{field} must be a finite Decimal.")
    try:
        normalized = value.quantize(_CENT)
    except InvalidOperation as error:
        raise InvalidBankStatementError(f"{field} uses unsupported precision.") from error
    if normalized != value or (positive and normalized <= 0):
        qualifier = "positive " if positive else ""
        raise InvalidBankStatementError(
            f"{field} must be a {qualifier}monetary value with at most two decimals."
        )
    return normalized


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidBankStatementError(f"{field} must be timezone-aware.")
    return value


def _score(value: Decimal, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or not Decimal("0") <= value <= 1:
        raise InvalidBankStatementError(f"{field} must be a Decimal between 0 and 1.")
    return value.quantize(_SCORE)


class BankMovementDirection(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class BankTransactionKind(StrEnum):
    TRANSFER = "TRANSFER"
    PAYMENT = "PAYMENT"
    RECEIPT = "RECEIPT"
    BANK_FEE = "BANK_FEE"
    INTEREST = "INTEREST"
    TAX = "TAX"
    OTHER = "OTHER"


class BankMovementStatus(StrEnum):
    PENDING = "PENDING"
    RECONCILED = "RECONCILED"


class BankStatementSource(StrEnum):
    OFX = "OFX"
    CSV = "CSV"


class BankStatementStatus(StrEnum):
    PENDING = "PENDING"
    PARTIALLY_RECONCILED = "PARTIALLY_RECONCILED"
    RECONCILED = "RECONCILED"


class ReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    PENDING = "PENDING"
    AMBIGUOUS = "AMBIGUOUS"


class ReconciliationReason(StrEnum):
    MATCHED = "MATCHED"
    DIRECTION_MISMATCH = "DIRECTION_MISMATCH"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    DATE_MISMATCH = "DATE_MISMATCH"
    DOCUMENT_MISMATCH = "DOCUMENT_MISMATCH"
    SCORE_BELOW_THRESHOLD = "SCORE_BELOW_THRESHOLD"
    NO_CANDIDATE = "NO_CANDIDATE"
    AMBIGUOUS_CANDIDATES = "AMBIGUOUS_CANDIDATES"


@dataclass(frozen=True, slots=True)
class BankMovement:
    id: UUID
    company_id: UUID
    bank_account_id: UUID
    external_id: str
    booked_on: date
    amount: Decimal
    direction: BankMovementDirection
    kind: BankTransactionKind
    description: str
    document_number: str | None = None
    status: BankMovementStatus = BankMovementStatus.PENDING
    matched_reference_id: UUID | None = None
    reconciled_at: datetime | None = None
    match_score: Decimal | None = None

    def __post_init__(self) -> None:
        for field in ("id", "company_id", "bank_account_id"):
            object.__setattr__(self, field, _uuid(getattr(self, field), field))
        object.__setattr__(self, "external_id", _text(self.external_id, "external_id", maximum=160))
        if not isinstance(self.booked_on, date):
            raise InvalidBankStatementError("booked_on must be a date.")
        object.__setattr__(self, "amount", _money(self.amount, "amount", positive=True))
        if not isinstance(self.direction, BankMovementDirection):
            raise InvalidBankStatementError("direction must be a BankMovementDirection.")
        if not isinstance(self.kind, BankTransactionKind):
            raise InvalidBankStatementError("kind must be a BankTransactionKind.")
        object.__setattr__(self, "description", _text(self.description, "description", maximum=500))
        object.__setattr__(
            self,
            "document_number",
            _optional_text(self.document_number, "document_number", maximum=120),
        )
        if not isinstance(self.status, BankMovementStatus):
            raise InvalidBankStatementError("status must be a BankMovementStatus.")
        evidence = (self.matched_reference_id, self.reconciled_at, self.match_score)
        if self.status is BankMovementStatus.PENDING and any(
            value is not None for value in evidence
        ):
            raise InvalidBankStatementError(
                "A pending movement cannot contain reconciliation evidence."
            )
        if self.status is BankMovementStatus.RECONCILED:
            if any(value is None for value in evidence):
                raise InvalidBankStatementError("A reconciled movement requires complete evidence.")
            assert self.matched_reference_id is not None
            assert self.reconciled_at is not None
            assert self.match_score is not None
            _uuid(self.matched_reference_id, "matched_reference_id")
            _aware(self.reconciled_at, "reconciled_at")
            object.__setattr__(self, "match_score", _score(self.match_score, "match_score"))

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.direction is BankMovementDirection.CREDIT else -self.amount

    def reconcile(
        self,
        *,
        reference_id: UUID,
        reconciled_at: datetime,
        score: Decimal,
    ) -> BankMovement:
        if self.status is BankMovementStatus.RECONCILED:
            raise BankMovementAlreadyReconciledError("Bank movement is already reconciled.")
        return replace(
            self,
            status=BankMovementStatus.RECONCILED,
            matched_reference_id=_uuid(reference_id, "reference_id"),
            reconciled_at=_aware(reconciled_at, "reconciled_at"),
            match_score=_score(score, "score"),
        )


@dataclass(frozen=True, slots=True)
class FinancialReconciliationCandidate:
    reference_id: UUID
    company_id: UUID
    expected_on: date
    amount: Decimal
    direction: BankMovementDirection
    document_number: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference_id", _uuid(self.reference_id, "reference_id"))
        object.__setattr__(self, "company_id", _uuid(self.company_id, "company_id"))
        if not isinstance(self.expected_on, date):
            raise InvalidBankStatementError("expected_on must be a date.")
        object.__setattr__(self, "amount", _money(self.amount, "amount", positive=True))
        if not isinstance(self.direction, BankMovementDirection):
            raise InvalidBankStatementError("direction must be a BankMovementDirection.")
        object.__setattr__(
            self,
            "document_number",
            _optional_text(self.document_number, "document_number", maximum=120),
        )


@dataclass(frozen=True, slots=True)
class ReconciliationTolerance:
    amount: Decimal = Decimal("0.01")
    date_days: int = 2
    document_similarity: Decimal = Decimal("0.80")
    auto_match_score: Decimal = Decimal("0.85")

    def __post_init__(self) -> None:
        normalized_amount = _money(self.amount, "amount_tolerance")
        if normalized_amount < 0:
            raise InvalidBankStatementError("amount_tolerance cannot be negative.")
        object.__setattr__(self, "amount", normalized_amount)
        if (
            not isinstance(self.date_days, int)
            or isinstance(self.date_days, bool)
            or not 0 <= self.date_days <= 31
        ):
            raise InvalidBankStatementError("date_days must be an integer between 0 and 31.")
        object.__setattr__(
            self,
            "document_similarity",
            _score(self.document_similarity, "document_similarity"),
        )
        object.__setattr__(
            self,
            "auto_match_score",
            _score(self.auto_match_score, "auto_match_score"),
        )


@dataclass(frozen=True, slots=True)
class ReconciliationSuggestion:
    movement_id: UUID
    candidate_id: UUID
    status: ReconciliationStatus
    reason: ReconciliationReason
    score: Decimal
    amount_delta: Decimal
    date_delta_days: int
    document_similarity: Decimal


@dataclass(frozen=True, slots=True)
class ReconciliationDecision:
    movement_id: UUID
    status: ReconciliationStatus
    reason: ReconciliationReason
    candidate_id: UUID | None = None
    score: Decimal | None = None


@dataclass(frozen=True, slots=True)
class BankReconciliationPolicy:
    tolerance: ReconciliationTolerance = ReconciliationTolerance()

    def evaluate(
        self,
        movement: BankMovement,
        candidate: FinancialReconciliationCandidate,
    ) -> ReconciliationSuggestion:
        if not isinstance(movement, BankMovement) or not isinstance(
            candidate, FinancialReconciliationCandidate
        ):
            raise InvalidBankStatementError(
                "Matching requires typed movement and candidate values."
            )
        if movement.company_id != candidate.company_id:
            raise FinanceScopeError("Movement and candidate must share company scope.")
        amount_delta = abs(movement.amount - candidate.amount)
        date_delta = abs((movement.booked_on - candidate.expected_on).days)
        document_similarity = _document_similarity(
            movement.document_number,
            candidate.document_number,
        )
        reason = self._blocking_reason(
            movement=movement,
            candidate=candidate,
            amount_delta=amount_delta,
            date_delta=date_delta,
            document_similarity=document_similarity,
        )
        score = self._weighted_score(
            amount_delta=amount_delta,
            date_delta=date_delta,
            document_similarity=document_similarity,
        )
        if reason is None and score < self.tolerance.auto_match_score:
            reason = ReconciliationReason.SCORE_BELOW_THRESHOLD
        status = ReconciliationStatus.MATCHED if reason is None else ReconciliationStatus.PENDING
        return ReconciliationSuggestion(
            movement_id=movement.id,
            candidate_id=candidate.reference_id,
            status=status,
            reason=reason or ReconciliationReason.MATCHED,
            score=score,
            amount_delta=amount_delta,
            date_delta_days=date_delta,
            document_similarity=document_similarity,
        )

    def best_match(
        self,
        movement: BankMovement,
        candidates: tuple[FinancialReconciliationCandidate, ...],
    ) -> ReconciliationDecision:
        suggestions = tuple(self.evaluate(movement, candidate) for candidate in candidates)
        matches = sorted(
            (item for item in suggestions if item.status is ReconciliationStatus.MATCHED),
            key=lambda item: (-item.score, str(item.candidate_id)),
        )
        if not matches:
            return ReconciliationDecision(
                movement.id,
                ReconciliationStatus.PENDING,
                ReconciliationReason.NO_CANDIDATE,
            )
        if len(matches) > 1 and matches[0].score == matches[1].score:
            return ReconciliationDecision(
                movement.id,
                ReconciliationStatus.AMBIGUOUS,
                ReconciliationReason.AMBIGUOUS_CANDIDATES,
                score=matches[0].score,
            )
        winner = matches[0]
        return ReconciliationDecision(
            movement.id,
            ReconciliationStatus.MATCHED,
            ReconciliationReason.MATCHED,
            candidate_id=winner.candidate_id,
            score=winner.score,
        )

    def _blocking_reason(
        self,
        *,
        movement: BankMovement,
        candidate: FinancialReconciliationCandidate,
        amount_delta: Decimal,
        date_delta: int,
        document_similarity: Decimal,
    ) -> ReconciliationReason | None:
        if movement.direction is not candidate.direction:
            return ReconciliationReason.DIRECTION_MISMATCH
        if amount_delta > self.tolerance.amount:
            return ReconciliationReason.AMOUNT_MISMATCH
        if date_delta > self.tolerance.date_days:
            return ReconciliationReason.DATE_MISMATCH
        if (
            movement.document_number is not None
            and candidate.document_number is not None
            and document_similarity < self.tolerance.document_similarity
        ):
            return ReconciliationReason.DOCUMENT_MISMATCH
        return None

    def _weighted_score(
        self,
        *,
        amount_delta: Decimal,
        date_delta: int,
        document_similarity: Decimal,
    ) -> Decimal:
        amount_score = _proximity(amount_delta, self.tolerance.amount)
        date_score = _proximity(Decimal(date_delta), Decimal(self.tolerance.date_days))
        value = (
            amount_score * Decimal("0.60")
            + date_score * Decimal("0.25")
            + document_similarity * Decimal("0.15")
        )
        return max(Decimal("0"), min(Decimal("1"), value)).quantize(_SCORE)


@dataclass(frozen=True, slots=True)
class BankStatement:
    id: UUID
    company_id: UUID
    bank_account_id: UUID
    bank_code: str
    account_reference: str
    period_start: date
    period_end: date
    imported_at: datetime
    source: BankStatementSource
    source_hash: str
    movements: tuple[BankMovement, ...]
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    version: int = 1

    def __post_init__(self) -> None:
        for field in ("id", "company_id", "bank_account_id"):
            object.__setattr__(self, field, _uuid(getattr(self, field), field))
        object.__setattr__(self, "bank_code", _text(self.bank_code, "bank_code", maximum=20))
        object.__setattr__(
            self,
            "account_reference",
            _text(self.account_reference, "account_reference", maximum=80),
        )
        if not isinstance(self.period_start, date) or not isinstance(self.period_end, date):
            raise InvalidBankStatementError("Statement period must use dates.")
        if self.period_start > self.period_end:
            raise InvalidBankStatementError("period_start cannot be after period_end.")
        _aware(self.imported_at, "imported_at")
        if not isinstance(self.source, BankStatementSource):
            raise InvalidBankStatementError("source must be a BankStatementSource.")
        normalized_hash = _text(self.source_hash, "source_hash", maximum=64).lower()
        if len(normalized_hash) != 64 or any(
            character not in "0123456789abcdef" for character in normalized_hash
        ):
            raise InvalidBankStatementError("source_hash must be a SHA-256 hexadecimal digest.")
        object.__setattr__(self, "source_hash", normalized_hash)
        if not isinstance(self.movements, tuple) or not self.movements:
            raise InvalidBankStatementError("movements must be a non-empty tuple.")
        movement_ids: set[UUID] = set()
        external_ids: set[str] = set()
        for movement in self.movements:
            if not isinstance(movement, BankMovement):
                raise InvalidBankStatementError("movements must contain BankMovement values.")
            if (
                movement.company_id != self.company_id
                or movement.bank_account_id != self.bank_account_id
            ):
                raise InvalidBankStatementError(
                    "Movements must share statement company and account."
                )
            if not self.period_start <= movement.booked_on <= self.period_end:
                raise InvalidBankStatementError(
                    "Movement date must be inside the statement period."
                )
            if movement.id in movement_ids or movement.external_id in external_ids:
                raise InvalidBankStatementError("Statement movements must be unique.")
            movement_ids.add(movement.id)
            external_ids.add(movement.external_id)
        if self.opening_balance is not None:
            object.__setattr__(
                self,
                "opening_balance",
                _money(self.opening_balance, "opening_balance"),
            )
        if self.closing_balance is not None:
            object.__setattr__(
                self,
                "closing_balance",
                _money(self.closing_balance, "closing_balance"),
            )
        if self.opening_balance is not None and self.closing_balance is not None:
            calculated = self.opening_balance + sum(
                (movement.signed_amount for movement in self.movements),
                start=Decimal("0.00"),
            )
            if abs(calculated - self.closing_balance) > _CENT:
                raise InvalidBankStatementError(
                    "Opening, movements and closing balance do not reconcile."
                )
        if type(self.version) is not int or self.version < 1:
            raise InvalidBankStatementError("version must be a positive integer.")

    @property
    def status(self) -> BankStatementStatus:
        reconciled = sum(
            movement.status is BankMovementStatus.RECONCILED for movement in self.movements
        )
        if reconciled == 0:
            return BankStatementStatus.PENDING
        if reconciled == len(self.movements):
            return BankStatementStatus.RECONCILED
        return BankStatementStatus.PARTIALLY_RECONCILED

    def movements_on(self, day: date) -> tuple[BankMovement, ...]:
        if not isinstance(day, date):
            raise InvalidBankStatementError("day must be a date.")
        return tuple(movement for movement in self.movements if movement.booked_on == day)

    def apply(
        self,
        decision: ReconciliationDecision,
        *,
        reconciled_at: datetime,
    ) -> BankStatement:
        return self.apply_many((decision,), reconciled_at=reconciled_at)

    def apply_many(
        self,
        decisions: tuple[ReconciliationDecision, ...],
        *,
        reconciled_at: datetime,
    ) -> BankStatement:
        if not isinstance(decisions, tuple) or not decisions:
            raise InvalidBankStatementError("decisions must be a non-empty tuple.")
        decision_by_movement: dict[UUID, ReconciliationDecision] = {}
        for decision in decisions:
            if not isinstance(decision, ReconciliationDecision):
                raise InvalidBankStatementError(
                    "decisions must contain ReconciliationDecision values."
                )
            if decision.status is not ReconciliationStatus.MATCHED:
                raise InvalidBankStatementError(
                    "Only an unambiguous match can reconcile a movement."
                )
            if decision.candidate_id is None or decision.score is None:
                raise InvalidBankStatementError(
                    "Matched decision requires candidate and score evidence."
                )
            if decision.movement_id in decision_by_movement:
                raise InvalidBankStatementError(
                    "A movement can receive only one reconciliation decision."
                )
            decision_by_movement[decision.movement_id] = decision
        changed: set[UUID] = set()
        movements: list[BankMovement] = []
        for movement in self.movements:
            selected = decision_by_movement.get(movement.id)
            if selected is not None:
                assert selected.candidate_id is not None
                assert selected.score is not None
                movement = movement.reconcile(
                    reference_id=selected.candidate_id,
                    reconciled_at=reconciled_at,
                    score=selected.score,
                )
                changed.add(movement.id)
            movements.append(movement)
        if changed != decision_by_movement.keys():
            raise InvalidBankStatementError("Decision movement does not belong to this statement.")
        return replace(self, movements=tuple(movements), version=self.version + 1)


def _document_similarity(left: str | None, right: str | None) -> Decimal:
    if left is None and right is None:
        return Decimal("0.5000")
    if left is None or right is None:
        return Decimal("0.0000")
    normalized_left = "".join(character for character in left.upper() if character.isalnum())
    normalized_right = "".join(character for character in right.upper() if character.isalnum())
    if not normalized_left or not normalized_right:
        return Decimal("0.0000")
    return Decimal(str(SequenceMatcher(None, normalized_left, normalized_right).ratio())).quantize(
        _SCORE
    )


def _proximity(delta: Decimal, tolerance: Decimal) -> Decimal:
    if delta == 0:
        return Decimal("1")
    if tolerance == 0 or delta > tolerance:
        return Decimal("0")
    return (Decimal("1") - delta / tolerance).quantize(_SCORE)


__all__ = [
    "BankMovement",
    "BankMovementDirection",
    "BankMovementStatus",
    "BankReconciliationPolicy",
    "BankStatement",
    "BankStatementSource",
    "BankStatementStatus",
    "BankTransactionKind",
    "FinancialReconciliationCandidate",
    "ReconciliationDecision",
    "ReconciliationReason",
    "ReconciliationStatus",
    "ReconciliationSuggestion",
    "ReconciliationTolerance",
]
