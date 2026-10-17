"""Strict adapters for CNAB return files and trusted PIX callback payloads."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from erp.modules.finance.application.settlement import (
    BankReturnDocument,
    BankReturnOutcome,
    BankSettlementNotification,
)
from erp.modules.finance.domain import BankRemittanceFormat, InvalidTreasuryRuleError

_CONFIRMED_CODES = {"00"}
_REJECTED_CODES = {"03", "AG", "CI"}


class Cnab240ReturnParser:
    def parse(self, content: bytes, *, company_id: UUID) -> BankReturnDocument:
        return _parse_cnab(
            content,
            company_id=company_id,
            width=240,
            remittance_format=BankRemittanceFormat.CNAB_240,
        )


class Cnab400ReturnParser:
    def parse(self, content: bytes, *, company_id: UUID) -> BankReturnDocument:
        return _parse_cnab(
            content,
            company_id=company_id,
            width=400,
            remittance_format=BankRemittanceFormat.CNAB_400,
        )


class PixCallbackParser:
    """Parse a signature-verified PIX callback supplied by the HTTP boundary."""

    def parse(self, content: bytes, *, company_id: UUID) -> BankReturnDocument:
        _company(company_id)
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidTreasuryRuleError("PIX callback must be valid UTF-8 JSON.") from error
        if not isinstance(payload, dict):
            raise InvalidTreasuryRuleError("PIX callback root must be an object.")
        record = _pix_record(payload, company_id=company_id)
        reference = _required_text(payload.get("event_id"), "event_id", maximum=120)
        return BankReturnDocument(BankRemittanceFormat.PIX_API, (record,), reference)


@dataclass(frozen=True, slots=True)
class BankReturnAdapterRegistry:
    """Select the bank-neutral parser without leaking formats into orchestration."""

    cnab_240: Cnab240ReturnParser = field(default_factory=Cnab240ReturnParser)
    cnab_400: Cnab400ReturnParser = field(default_factory=Cnab400ReturnParser)
    pix_api: PixCallbackParser = field(default_factory=PixCallbackParser)

    def parse(
        self,
        remittance_format: BankRemittanceFormat,
        content: bytes,
        *,
        company_id: UUID,
    ) -> BankReturnDocument:
        if remittance_format is BankRemittanceFormat.CNAB_240:
            return self.cnab_240.parse(content, company_id=company_id)
        if remittance_format is BankRemittanceFormat.CNAB_400:
            return self.cnab_400.parse(content, company_id=company_id)
        if remittance_format is BankRemittanceFormat.PIX_API:
            return self.pix_api.parse(content, company_id=company_id)
        raise InvalidTreasuryRuleError("Unsupported bank return format.")


def _parse_cnab(
    content: bytes,
    *,
    company_id: UUID,
    width: int,
    remittance_format: BankRemittanceFormat,
) -> BankReturnDocument:
    _company(company_id)
    try:
        lines = content.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise InvalidTreasuryRuleError("CNAB return must contain ASCII data.") from error
    if len(lines) < 3 or any(len(line) != width for line in lines):
        raise InvalidTreasuryRuleError(
            f"CNAB {width} return requires fixed-width header, details and trailer."
        )
    if lines[0][0] != "0" or lines[-1][0] != "9":
        raise InvalidTreasuryRuleError("CNAB return requires header type 0 and trailer type 9.")
    details = tuple(line for line in lines[1:-1] if line[0] == "3")
    if not details or len(details) != len(lines) - 2:
        raise InvalidTreasuryRuleError("CNAB return contains unsupported record types.")
    records = tuple(_cnab_record(line, company_id=company_id) for line in details)
    reference = _required_text(lines[0][1:41], "source_reference", maximum=40)
    return BankReturnDocument(remittance_format, records, reference)


def _cnab_record(line: str, *, company_id: UUID) -> BankSettlementNotification:
    try:
        payment_batch_id = UUID(hex=line[1:33])
    except ValueError as error:
        raise InvalidTreasuryRuleError(
            "CNAB return contains an invalid payment batch id."
        ) from error
    protocol = _required_text(line[33:73], "protocol", maximum=40)
    status_code = _required_text(line[73:75], "status_code", maximum=2).upper()
    amount = _amount(line[75:93])
    occurred_at = _date_time(line[93:101])
    reason = line[101:181].strip() or None
    outcome = _outcome(status_code)
    if outcome is BankReturnOutcome.CONFIRMED and amount is None:
        raise InvalidTreasuryRuleError("Confirmed CNAB records require a positive amount.")
    if outcome is not BankReturnOutcome.CONFIRMED and reason is None:
        raise InvalidTreasuryRuleError("Rejected CNAB records require a reason.")
    return BankSettlementNotification(
        company_id=company_id,
        payment_batch_id=payment_batch_id,
        protocol=protocol,
        status_code=status_code,
        outcome=outcome,
        occurred_at=occurred_at,
        amount=amount,
        reason=reason,
    )


def _pix_record(payload: dict[str, Any], *, company_id: UUID) -> BankSettlementNotification:
    status = _required_text(payload.get("status"), "status", maximum=16).upper()
    try:
        outcome = BankReturnOutcome(status)
        payment_batch_id = UUID(
            _required_text(payload.get("payment_batch_id"), "payment_batch_id", maximum=36)
        )
        occurred_at = datetime.fromisoformat(
            _required_text(payload.get("occurred_at"), "occurred_at", maximum=40)
        )
    except ValueError as error:
        raise InvalidTreasuryRuleError("PIX callback contains invalid typed fields.") from error
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise InvalidTreasuryRuleError("PIX occurred_at must be timezone-aware.")
    amount = _decimal_amount(payload.get("amount"))
    reason_value = payload.get("reason")
    reason = None if reason_value is None else _required_text(reason_value, "reason", maximum=500)
    if outcome is BankReturnOutcome.CONFIRMED and amount is None:
        raise InvalidTreasuryRuleError("Confirmed PIX callbacks require amount.")
    if outcome is not BankReturnOutcome.CONFIRMED and reason is None:
        raise InvalidTreasuryRuleError("Failed PIX callbacks require reason.")
    return BankSettlementNotification(
        company_id=company_id,
        payment_batch_id=payment_batch_id,
        protocol=_required_text(payload.get("protocol"), "protocol", maximum=120),
        status_code=_required_text(payload.get("status_code"), "status_code", maximum=40),
        outcome=outcome,
        occurred_at=occurred_at,
        amount=amount,
        reason=reason,
    )


def _outcome(status_code: str) -> BankReturnOutcome:
    if status_code in _CONFIRMED_CODES:
        return BankReturnOutcome.CONFIRMED
    if status_code in _REJECTED_CODES:
        return BankReturnOutcome.REJECTED
    return BankReturnOutcome.FAILED


def _amount(value: str) -> Decimal | None:
    normalized = value.strip()
    if not normalized:
        return None
    if not normalized.isdigit():
        raise InvalidTreasuryRuleError("CNAB amount must contain only digits.")
    amount = (Decimal(normalized) / Decimal("100")).quantize(Decimal("0.01"))
    return amount if amount > 0 else None


def _decimal_amount(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as error:
        raise InvalidTreasuryRuleError("PIX amount must be monetary.") from error
    if not amount.is_finite() or amount <= 0:
        raise InvalidTreasuryRuleError("PIX amount must be positive.")
    return amount


def _date_time(value: str) -> datetime:
    try:
        parsed = datetime.strptime(f"{value}+0000", "%Y%m%d%z")
    except ValueError as error:
        raise InvalidTreasuryRuleError("CNAB occurrence date must use YYYYMMDD.") from error
    return parsed.astimezone(UTC)


def _required_text(value: Any, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidTreasuryRuleError(f"{field} must be text.")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise InvalidTreasuryRuleError(f"{field} must contain between 1 and {maximum} characters.")
    return normalized


def _company(company_id: UUID) -> None:
    if not isinstance(company_id, UUID) or company_id.int == 0:
        raise InvalidTreasuryRuleError("company_id must be a non-zero UUID.")


__all__ = [
    "BankReturnAdapterRegistry",
    "Cnab240ReturnParser",
    "Cnab400ReturnParser",
    "PixCallbackParser",
]
