"""Duplicate detection and merge request primitives for M14 customer records."""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from uuid import UUID, uuid4

from erp.modules.customer.domain.customer import Customer


class DuplicateReason(StrEnum):
    EXACT_IDENTITY = "EXACT_IDENTITY"
    LEGAL_NAME_SIMILAR = "LEGAL_NAME_SIMILAR"
    TRADE_NAME_SIMILAR = "TRADE_NAME_SIMILAR"


class MergeRequestStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"


@dataclass(frozen=True, slots=True)
class CustomerDuplicateCandidate:
    id: UUID
    company_id: UUID
    source_customer_id: UUID
    candidate_customer_id: UUID
    confidence: int
    reason_codes: tuple[DuplicateReason, ...]

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (
                self.id,
                self.company_id,
                self.source_customer_id,
                self.candidate_customer_id,
            )
        ):
            raise ValueError("Duplicate candidate identity and customer references must be UUIDs.")
        if self.source_customer_id == self.candidate_customer_id:
            raise ValueError("Duplicate candidates require two different customers.")
        if not isinstance(self.confidence, int) or not 0 <= self.confidence <= 100:
            raise ValueError("confidence must be an integer between 0 and 100.")
        if not self.reason_codes or any(
            not isinstance(reason, DuplicateReason) for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain official duplicate reasons.")


@dataclass(frozen=True, slots=True)
class CustomerMergeRequest:
    id: UUID
    company_id: UUID
    source_customer_id: UUID
    candidate_customer_id: UUID
    surviving_customer_id: UUID
    status: MergeRequestStatus
    reason: str
    version: int

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID)
            for value in (
                self.id,
                self.company_id,
                self.source_customer_id,
                self.candidate_customer_id,
                self.surviving_customer_id,
            )
        ):
            raise ValueError("Merge request identity and customer references must be UUIDs.")
        if self.source_customer_id == self.candidate_customer_id:
            raise ValueError("Merge requests require two different customers.")
        if self.surviving_customer_id not in (self.source_customer_id, self.candidate_customer_id):
            raise ValueError("surviving_customer_id must be one of the requested customers.")
        if not isinstance(self.status, MergeRequestStatus):
            raise ValueError("status must be an official merge request status.")
        if not 1 <= len(self.reason) <= 500 or self.reason != self.reason.strip():
            raise ValueError("reason must contain 1 to 500 trimmed characters.")
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError("version must be a positive integer.")

    @classmethod
    def request(
        cls,
        *,
        company_id: UUID,
        source_customer_id: UUID,
        candidate_customer_id: UUID,
        surviving_customer_id: UUID,
        reason: str,
    ) -> CustomerMergeRequest:
        return cls(
            id=uuid4(),
            company_id=company_id,
            source_customer_id=source_customer_id,
            candidate_customer_id=candidate_customer_id,
            surviving_customer_id=surviving_customer_id,
            status=MergeRequestStatus.PENDING_APPROVAL,
            reason=reason.strip(),
            version=1,
        )


def detect_duplicate_candidates(
    source: Customer,
    candidates: tuple[Customer, ...],
    *,
    similarity_threshold: int = 86,
) -> tuple[CustomerDuplicateCandidate, ...]:
    if not 1 <= similarity_threshold <= 100:
        raise ValueError("similarity_threshold must be between 1 and 100.")
    detected: list[CustomerDuplicateCandidate] = []
    for candidate in candidates:
        if candidate.company_id != source.company_id or candidate.id == source.id:
            continue
        reasons: list[DuplicateReason] = []
        confidence = 0
        if candidate.tax_id == source.tax_id:
            reasons.append(DuplicateReason.EXACT_IDENTITY)
            confidence = 100
        else:
            legal_score = _similarity(source.legal_name, candidate.legal_name)
            if legal_score >= similarity_threshold:
                reasons.append(DuplicateReason.LEGAL_NAME_SIMILAR)
                confidence = max(confidence, legal_score)
            if source.trade_name is not None and candidate.trade_name is not None:
                trade_score = _similarity(source.trade_name, candidate.trade_name)
                if trade_score >= similarity_threshold:
                    reasons.append(DuplicateReason.TRADE_NAME_SIMILAR)
                    confidence = max(confidence, trade_score)
        if reasons:
            detected.append(
                CustomerDuplicateCandidate(
                    id=uuid4(),
                    company_id=source.company_id,
                    source_customer_id=source.id,
                    candidate_customer_id=candidate.id,
                    confidence=confidence,
                    reason_codes=tuple(dict.fromkeys(reasons)),
                )
            )
    return tuple(
        sorted(detected, key=lambda item: (-item.confidence, str(item.candidate_customer_id)))
    )


def _similarity(left: str, right: str) -> int:
    normalized_left, normalized_right = _normalize(left), _normalize(right)
    if not normalized_left or not normalized_right:
        return 0
    return round(SequenceMatcher(None, normalized_left, normalized_right).ratio() * 100)


def _normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", ascii_value.upper())).strip()


__all__ = [
    "CustomerDuplicateCandidate",
    "CustomerMergeRequest",
    "DuplicateReason",
    "MergeRequestStatus",
    "detect_duplicate_candidates",
]
